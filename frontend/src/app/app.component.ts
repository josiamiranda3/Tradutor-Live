
import { CommonModule } from '@angular/common';
import { Component, NgZone, OnDestroy } from '@angular/core';
import { environment } from '../environments/environment';

type ServerEvent = {
  type?: string;
  message?: string;
  delta?: string;
  transcript?: string;
  sequence?: number;
  error?: { message?: string };
};

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent implements OnDestroy {
  constructor(private readonly zone: NgZone) {}

  status = 'Pronto para iniciar';
  statusMode: 'idle' | 'active' | 'error' = 'idle';
  connected = false;

  englishFinal = '';
  englishDelta = '';
  portugueseFinal = '';
  portugueseDelta = '';
  errorMessage = '';

  private socket: WebSocket | null = null;

  get englishText(): string {
    return [
      this.englishFinal,
      this.englishDelta,
    ]
      .filter(Boolean)
      .join(
        this.englishFinal && this.englishDelta ? '\n' : '',
      );
  }

  get portugueseText(): string {
    return [
      this.portugueseFinal,
      this.portugueseDelta,
    ]
      .filter(Boolean)
      .join(
        this.portugueseFinal && this.portugueseDelta ? '\n' : '',
      );
  }

  start(): void {
    // Impede conexões duplicadas enquanto conecta ou está conectado.
    if (
      this.socket &&
      (
        this.socket.readyState === WebSocket.CONNECTING ||
        this.socket.readyState === WebSocket.OPEN
      )
    ) {
      return;
    }

    this.errorMessage = '';
    this.connected = true;
    this.status = 'Conectando ao backend local…';
    this.statusMode = 'idle';

    try {
      const socket = new WebSocket(
        environment.backendWebSocketUrl,
      );

      this.socket = socket;

      socket.onopen = () => {
        this.zone.run(() => {
          this.status = 'Conectado; preparando captura do Windows…';
          this.statusMode = 'active';

          socket.send(JSON.stringify({ type: 'start' }));
        });
      };

      socket.onmessage = (message: MessageEvent<string>) => {
        this.zone.run(() => {
          try {
            const event = JSON.parse(
              message.data,
            ) as ServerEvent;

            console.log('[WebSocket recebido]', {
              time: new Date().toLocaleTimeString(),
              type: event.type,
              delta: event.delta,
              transcript: event.transcript,
              message: event.message,
            });

            this.handleEvent(event);
          } catch {
            this.fail(
              'O backend enviou uma mensagem inválida.',
            );
          }
        });
      };

      socket.onerror = () => {
        this.zone.run(() => {
          this.fail(
            'Não foi possível conectar ao backend local. Confira se o FastAPI está rodando.',
          );
        });
      };

      socket.onclose = () => {
        this.zone.run(() => {
          // Evita alterar o estado de uma conexão mais recente.
          if (this.socket !== socket) {
            return;
          }

          this.connected = false;
          this.socket = null;

          if (this.statusMode !== 'error') {
            this.status = 'Sessão encerrada';
          }
        });
      };
    } catch (error) {
      this.connected = false;
      this.socket = null;

      this.fail(
        error instanceof Error
          ? error.message
          : 'Não foi possível abrir o WebSocket.',
      );
    }
  }

  stop(): void {
    const socket = this.socket;

    if (!socket) {
      this.connected = false;
      return;
    }

    if (socket.readyState === WebSocket.OPEN) {
      this.status = 'Encerrando sessão…';
      this.statusMode = 'idle';

      // Solicita o encerramento e aguarda o backend.
      // Não fecha o WebSocket à força após dois segundos.
      socket.send(JSON.stringify({ type: 'stop' }));
    } else if (socket.readyState === WebSocket.CONNECTING) {
      this.status = 'A conexão ainda está sendo estabelecida.';
      return;
    } else {
      this.connected = false;
      this.socket = null;
    }
  }

  clear(): void {
    this.englishFinal = '';
    this.englishDelta = '';
    this.portugueseFinal = '';
    this.portugueseDelta = '';
    this.errorMessage = '';
  }

  copy(text: string): void {
    if (!text.trim()) {
      this.fail('Ainda não há texto para copiar.');
      return;
    }

    navigator.clipboard.writeText(text)
      .then(() => {
        this.status = 'Texto copiado';
        this.statusMode = 'active';
      })
      .catch(() => {
        this.fail(
          'Não foi possível copiar automaticamente.',
        );
      });
  }

  ngOnDestroy(): void {
    this.socket?.close();
  }

  private handleEvent(event: ServerEvent): void {
    switch (event.type) {
      case 'app.status':
        this.status =
          event.message ?? 'Capturando áudio…';
        this.statusMode = 'active';
        break;

      case 'session.created':
        this.status =
          event.message ?? 'Gemini conectado';
        this.statusMode = 'active';
        break;

      case 'session.input_transcript.delta':
        this.englishDelta = event.delta ?? '';
        break;

      case 'session.input_transcript.done': {
        const text = (
          event.transcript ?? this.englishDelta
        ).trim();

        if (text) {
          this.englishFinal +=
            (this.englishFinal ? '\n' : '') + text;
        }

        this.englishDelta = '';
        break;
      }

      case 'session.output_transcript.delta':
        this.portugueseDelta += event.delta ?? '';
        break;

      case 'session.output_transcript.done': {
        const text = (
          event.transcript ?? this.portugueseDelta
        ).trim();

        if (text) {
          this.portugueseFinal +=
            (this.portugueseFinal ? '\n' : '') + text;
        }

        this.portugueseDelta = '';
        break;
      }

      case 'app.error':
      case 'error':
        this.fail(
          event.message ??
          event.error?.message ??
          'Erro durante a tradução.',
        );
        break;

      case 'session.closed':
        this.status =
          event.message ?? 'Sessão encerrada';
        this.statusMode = 'idle';
        break;
    }
  }

  private fail(message: string): void {
    this.errorMessage = message;
    this.status = 'Verifique a conexão';
    this.statusMode = 'error';
  }
}
