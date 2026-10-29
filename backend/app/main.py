
from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path

import numpy as np
import scipy.signal
import soundcard as sc
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TRANSCRIPTION_MODEL = os.getenv(
    "GEMINI_TRANSCRIPTION_MODEL",
    "gemini-3.5-transcribe-live",
).strip()
TRANSLATION_MODEL = os.getenv(
    "GEMINI_TRANSLATION_MODEL",
    "gemini-3.5-flash-lite",
).strip()
TARGET_LANGUAGE = os.getenv(
    "TARGET_LANGUAGE",
    "Portuguese (Brazilian Portuguese)",
).strip()

SOURCE_SAMPLE_RATE = 48000
TARGET_SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.10

app = FastAPI(
    title="Tradutor de Voz Live",
    version="3.0.0",
    description=(
        "Tradutor contínuo do áudio de saída do Windows "
        "para legendas em português usando Gemini."
    ),
)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "api_key_configured": bool(API_KEY),
        "transcription_model": TRANSCRIPTION_MODEL,
        "translation_model": TRANSLATION_MODEL,
        "target_language": TARGET_LANGUAGE,
        "capture": "Windows WASAPI loopback via SoundCard",
        "provider": "Google Gemini Live API",
    }


def _loopback_microphone():
    """Localiza o dispositivo padrão de saída do Windows."""
    speaker = sc.default_speaker()

    if speaker is None:
        raise RuntimeError(
            "O Windows não informou um dispositivo de saída padrão."
        )

    mic = sc.get_microphone(
        id=str(speaker.name),
        include_loopback=True,
    )

    if mic is None:
        raise RuntimeError(
            f"Não foi possível abrir a captura loopback: {speaker.name}"
        )

    return speaker, mic


def _convert_audio_chunk(audio) -> bytes:
    """Converte áudio para PCM16 mono a 16 kHz."""
    if audio is None or len(audio) == 0:
        return bytes(int(TARGET_SAMPLE_RATE * CHUNK_SECONDS * 2))

    audio = np.asarray(audio, dtype=np.float32)

    if audio.ndim == 2:
        audio = np.mean(audio, axis=1)

    audio = np.clip(audio, -1.0, 1.0)

    audio_16k = scipy.signal.resample_poly(
        audio,
        up=1,
        down=3,
    )

    pcm16 = (
        np.clip(audio_16k, -1.0, 1.0) * 32767
    ).astype("<i2")

    return pcm16.tobytes()


async def _capture_and_send(mic, session, client_ws: WebSocket):
    """Mantém um gravador WASAPI persistente durante a sessão."""
    import concurrent.futures

    frames = int(SOURCE_SAMPLE_RATE * CHUNK_SECONDS)
    loop = asyncio.get_running_loop()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="wasapi-capture",
    ) as executor:
        recorder = mic.recorder(
            samplerate=SOURCE_SAMPLE_RATE,
        )
        entered = False

        try:
            await loop.run_in_executor(
                executor,
                recorder.__enter__,
            )
            entered = True

            while True:
                audio = await loop.run_in_executor(
                    executor,
                    recorder.record,
                    frames,
                )

                pcm = _convert_audio_chunk(audio)

                await session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm,
                        mime_type="audio/pcm;rate=16000",
                    )
                )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[ERRO CAPTURA] {type(exc).__name__}: {exc}",
                flush=True,
            )

            with suppress(Exception):
                await client_ws.send_json({
                    "type": "app.error",
                    "message": (
                        "Falha ao capturar/enviar áudio do Windows: "
                        f"{exc}"
                    ),
                })

            raise

        finally:
            if entered:
                with suppress(Exception):
                    await loop.run_in_executor(
                        executor,
                        recorder.__exit__,
                        None,
                        None,
                        None,
                    )


async def _translate_text(
    client: genai.Client,
    text: str,
    client_ws: WebSocket,
    sequence: int,
):
    """Traduz um trecho finalizado sem bloquear a recepção."""
    try:
        prompt = (
            "Translate the following spoken English into natural "
            "Brazilian Portuguese. Return only the translation, "
            "preserving the meaning and tone. Do not explain.\n\n"
            f"English: {text}"
        )

        response = await client.aio.models.generate_content(
            model=TRANSLATION_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1024,
            ),
        )

        translated = (response.text or "").strip()

        if translated:
            await client_ws.send_json({
                "type": "session.output_transcript.delta",
                "delta": translated,
                "sequence": sequence,
            })

            await client_ws.send_json({
                "type": "session.output_transcript.done",
                "transcript": translated,
                "sequence": sequence,
            })

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        print(
            f"[ERRO TRADUÇÃO] {type(exc).__name__}: {exc}",
            flush=True,
        )

        with suppress(Exception):
            await client_ws.send_json({
                "type": "app.error",
                "message": (
                    "Erro ao traduzir um trecho pelo Gemini: "
                    f"{exc}"
                ),
            })


async def _receive_transcripts(
    session,
    client: genai.Client,
    client_ws: WebSocket,
):
    """Recebe e registra eventos de transcrição do Gemini."""
    sequence = 0
    pending_translations: set[asyncio.Task] = set()

    try:
        async for response in session.receive():
            content = getattr(
                response,
                "server_content",
                None,
            )

            interim = getattr(
                content,
                "interim_input_transcription",
                None,
            ) if content is not None else None

            final = getattr(
                content,
                "input_transcription",
                None,
            ) if content is not None else None

            print(
                "[GEMINI EVENTO]",
                f"content={content is not None}",
                f"interim={getattr(interim, 'text', None)!r}",
                f"final={getattr(final, 'text', None)!r}",
                flush=True,
            )

            if content is None:
                continue

            if interim and getattr(interim, "text", None):
                await client_ws.send_json({
                    "type": "session.input_transcript.delta",
                    "delta": interim.text,
                })

            if final and getattr(final, "text", None):
                text = final.text.strip()

                if text:
                    sequence += 1

                    await client_ws.send_json({
                        "type": "session.input_transcript.done",
                        "transcript": text,
                        "sequence": sequence,
                    })

                    task = asyncio.create_task(
                        _translate_text(
                            client,
                            text,
                            client_ws,
                            sequence,
                        )
                    )

                    pending_translations.add(task)
                    task.add_done_callback(
                        pending_translations.discard
                    )

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        print(
            f"[ERRO RECEPÇÃO] {type(exc).__name__}: {exc}",
            flush=True,
        )

        with suppress(Exception):
            await client_ws.send_json({
                "type": "app.error",
                "message": (
                    "Erro ao receber transcrições do Gemini: "
                    f"{exc}"
                ),
            })

    finally:
        if pending_translations:
            await asyncio.gather(
                *pending_translations,
                return_exceptions=True,
            )


@app.websocket("/ws/translation")
async def translation_socket(client_ws: WebSocket):
    await client_ws.accept()

    if not API_KEY:
        await client_ws.send_json({
            "type": "app.error",
            "message": (
                "GEMINI_API_KEY não configurada. "
                "Confira o arquivo .env do backend."
            ),
        })
        await client_ws.close(code=1011)
        return

    try:
        speaker, mic = await asyncio.to_thread(
            _loopback_microphone,
        )

    except Exception as exc:
        await client_ws.send_json({
            "type": "app.error",
            "message": (
                "Não foi possível iniciar a captura do áudio "
                f"do Windows: {exc}"
            ),
        })
        await client_ws.close(code=1011)
        return

    client = genai.Client(api_key=API_KEY)

    await client_ws.send_json({
        "type": "app.status",
        "message": f"Capturando áudio do Windows: {speaker.name}",
    })

    try:
        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

        async with client.aio.live.connect(
            model=TRANSCRIPTION_MODEL,
            config=config,
        ) as session:
            await client_ws.send_json({
                "type": "session.created",
                "message": "Gemini conectado. Ouvindo áudio em inglês…",
            })

            capture_task = asyncio.create_task(
                _capture_and_send(
                    mic,
                    session,
                    client_ws,
                )
            )

            receive_task = asyncio.create_task(
                _receive_transcripts(
                    session,
                    client,
                    client_ws,
                )
            )

            try:
                while True:
                    message = await client_ws.receive_json()

                    if message.get("type") == "stop":
                        print(
                            "[SESSÃO] Solicitação de encerramento recebida.",
                            flush=True,
                        )
                        break

            except WebSocketDisconnect:
                print(
                    "[SESSÃO] Cliente desconectado.",
                    flush=True,
                )

            finally:
                # Para a captura antes de sinalizar o fim do áudio.
                capture_task.cancel()

                with suppress(asyncio.CancelledError, Exception):
                    await capture_task

                # Envia o sinal de fim de áudio ao Gemini.
                with suppress(Exception):
                    await session.send_realtime_input(
                        audio_stream_end=True,
                    )

                # Aguarda os eventos finais por tempo limitado.
                try:
                    await asyncio.wait_for(
                        asyncio.shield(receive_task),
                        timeout=5.0,
                    )

                except asyncio.TimeoutError:
                    print(
                        "[SESSÃO] Timeout aguardando eventos finais.",
                        flush=True,
                    )

                    receive_task.cancel()

                    with suppress(
                        asyncio.CancelledError,
                        Exception,
                    ):
                        await receive_task

                except Exception as exc:
                    print(
                        f"[SESSÃO] Recepção encerrada: {exc}",
                        flush=True,
                    )

            with suppress(Exception):
                await client_ws.send_json({
                    "type": "session.closed",
                    "message": "Tradução encerrada.",
                })

    except WebSocketDisconnect:
        pass

    except Exception as exc:
        print(
            f"[ERRO GEMINI LIVE] {type(exc).__name__}: {exc}",
            flush=True,
        )

        with suppress(Exception):
            await client_ws.send_json({
                "type": "app.error",
                "message": f"Falha na sessão Gemini: {exc}",
            })

    finally:
        with suppress(Exception):
            await client_ws.close()
