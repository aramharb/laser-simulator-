import { Injectable, signal } from '@angular/core';
import { Observable, filter } from 'rxjs';

export interface ShootOffShotEvent {
  event: 'shot';
  x: number;
  y: number;
  timestamp: number;
  raw_x?: number;
  raw_y?: number;
  color?: string;
  confidence?: number;
}

export interface ShootOffCalibrationStatus {
  status: 'manual_adjusting' | 'calibrated' | 'calibration_failed';
  bbox?: [number, number, number, number];
  mode?: 'manual' | 'cached' | 'zhang_4pt' | 'zhang_2pt_affine';
  reason?: string;
  confidence?: number;
  elapsed_seconds?: number;
  arena_w?: number;
  arena_h?: number;
  has_homography?: boolean;
}

export interface ShootOffErrorMessage {
  error: string;
}

export interface ShootOffSocketOptions {
  debugPreview?: boolean;
  calibrate?: boolean;
  arenaWidth?: number;
  arenaHeight?: number;
}

export type ShootOffMessage = ShootOffShotEvent | ShootOffCalibrationStatus | ShootOffErrorMessage;

const SHOOTOFF_SOCKET_PATH = '/api/ws/shots';
const DEFAULT_SOCKET_TIMEOUT_MS = 5000;

@Injectable({ providedIn: 'root' })
export class ShootOffSocketService {
  /**
   * Signal to track connection state: 'disconnected' | 'connecting' | 'connected' | 'error'
   */
  readonly connectionState = signal<'disconnected' | 'connecting' | 'connected' | 'error'>('disconnected');

  /**
   * Signal to track last connection error
   */
  readonly lastError = signal<string | null>(null);

  /**
   * Connect to the ShootOff WebSocket API and get all messages
   * @param options Configuration options (debugPreview, calibrate)
   * @returns Observable of all ShootOff messages
   */
  connect(options: ShootOffSocketOptions = {}): Observable<ShootOffMessage> {
    return new Observable((observer) => {
      this.connectionState.set('connecting');
      const socket = new WebSocket(this.resolveSocketUrl(options));
      let timeoutHandle: number | undefined;

      const clearTimeout = () => {
        if (timeoutHandle !== undefined) {
          window.clearTimeout(timeoutHandle);
          timeoutHandle = undefined;
        }
      };

      const handleMessage = (event: MessageEvent) => {
        if (typeof event.data !== 'string') {
          return;
        }

        try {
          const payload = JSON.parse(event.data) as ShootOffMessage;
          observer.next(payload);
        } catch (error) {
          console.warn('Failed to parse ShootOff message:', error);
        }
      };

      const handleError = (event: Event) => {
        clearTimeout();
        const errorMsg = 'ShootOff WebSocket connection error';
        this.lastError.set(errorMsg);
        this.connectionState.set('error');
        console.error(errorMsg, event);
        observer.error(new Error(errorMsg));
      };

      const handleClose = () => {
        clearTimeout();
        this.connectionState.set('disconnected');
        observer.complete();
      };

      const handleOpen = () => {
        clearTimeout();
        this.connectionState.set('connected');
        this.lastError.set(null);
      };

      // Set connection timeout
      timeoutHandle = window.setTimeout(() => {
        if (socket.readyState !== WebSocket.OPEN) {
          socket.close();
          handleError(new Event('timeout'));
        }
      }, DEFAULT_SOCKET_TIMEOUT_MS);

      socket.addEventListener('open', handleOpen);
      socket.addEventListener('message', handleMessage);
      socket.addEventListener('error', handleError);
      socket.addEventListener('close', handleClose);

      return () => {
        clearTimeout();
        socket.removeEventListener('open', handleOpen);
        socket.removeEventListener('message', handleMessage);
        socket.removeEventListener('error', handleError);
        socket.removeEventListener('close', handleClose);

        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
          socket.close();
        }
      };
    });
  }

  /**
   * Connect and get only shot events, filtering out calibration messages
   * @param options Configuration options
   * @returns Observable of shot events only
   */
  connectToShots(options: ShootOffSocketOptions = {}): Observable<ShootOffShotEvent> {
    return this.connect(options).pipe(
      filter((msg): msg is ShootOffShotEvent => 'event' in msg && msg.event === 'shot'),
    );
  }

  /**
   * Connect and get only calibration status messages, filtering out shot events
   * @param options Configuration options
   * @returns Observable of calibration status messages only
   */
  connectToCalibration(options: ShootOffSocketOptions = {}): Observable<ShootOffCalibrationStatus> {
    return this.connect(options).pipe(
      filter((msg): msg is ShootOffCalibrationStatus => 'status' in msg),
    );
  }

  /**
   * Connect and get only error messages
   * @param options Configuration options
   * @returns Observable of error messages only
   */
  connectToErrors(options: ShootOffSocketOptions = {}): Observable<ShootOffErrorMessage> {
    return this.connect(options).pipe(
      filter((msg): msg is ShootOffErrorMessage => 'error' in msg),
    );
  }

  /**
   * Type guard to check if message is a shot event
   */
  isShotEvent(message: ShootOffMessage): message is ShootOffShotEvent {
    return 'event' in message && message.event === 'shot';
  }

  /**
   * Type guard to check if message is a calibration status
   */
  isCalibrationStatus(message: ShootOffMessage): message is ShootOffCalibrationStatus {
    return 'status' in message;
  }

  /**
   * Type guard to check if message is an error
   */
  isErrorMessage(message: ShootOffMessage): message is ShootOffErrorMessage {
    return 'error' in message;
  }

  /**
   * Resolve the WebSocket URL based on the current environment and options
   */
  private resolveSocketUrl(options: ShootOffSocketOptions): string {
    if (typeof window === 'undefined') {
      return `ws://localhost:8000${SHOOTOFF_SOCKET_PATH}`;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || 'localhost:4200';
    const params = new URLSearchParams();
    
    if (options.debugPreview) {
      params.set('debug', '1');
    }
    if (options.calibrate) {
      params.set('calibrate', '1');
    }
    if (Number.isFinite(options.arenaWidth) && (options.arenaWidth ?? 0) > 0) {
      params.set('arena_w', String(Math.round(options.arenaWidth!)));
    }
    if (Number.isFinite(options.arenaHeight) && (options.arenaHeight ?? 0) > 0) {
      params.set('arena_h', String(Math.round(options.arenaHeight!)));
    }
    
    const query = params.toString();
    const url = query
      ? `${protocol}//${host}${SHOOTOFF_SOCKET_PATH}?${query}`
      : `${protocol}//${host}${SHOOTOFF_SOCKET_PATH}`;
    
    // Debug: Log arena dimensions being sent
    if (options.arenaWidth || options.arenaHeight) {
      console.log(
        `[ShootOffSocket] Connecting with arena size: ${Math.round(options.arenaWidth ?? 0)} x ${Math.round(options.arenaHeight ?? 0)}`,
        { arenaWidth: options.arenaWidth, arenaHeight: options.arenaHeight, url }
      );
    }
    
    return url;
  }
}
