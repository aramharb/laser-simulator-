# ShootOFF Socket Service - Usage Guide

This guide explains how to use the `ShootOffSocketService` to conveniently integrate with the Python `api.py` backend.

## Overview

The service provides WebSocket communication with the ShootOFF Python backend for:
- **Shot Detection**: Receive calibrated shot coordinates
- **Calibration**: Track projector/camera calibration status
- **Error Handling**: Monitor connection and operation errors

## Basic Connection

### Connect to All Messages
```typescript
import { ShootOffSocketService } from './shootoff-socket.service';

export class MyComponent {
  private shootOffService = inject(ShootOffSocketService);

  ngOnInit() {
    this.shootOffService.connect().subscribe({
      next: (message) => {
        // message can be ShootOffShotEvent, ShootOffCalibrationStatus, or ShootOffErrorMessage
        console.log('Received:', message);
      },
      error: (err) => console.error('Connection error:', err),
    });
  }
}
```

## Convenient Filtered Streams

### Listen Only to Shots
Perfect for game logic that just needs shot coordinates:
```typescript
this.shootOffService.connectToShots().subscribe({
  next: (shot) => {
    console.log(`Shot at (${shot.x}, ${shot.y}) with confidence ${shot.confidence}`);
    // Process shot in your game
  },
});
```

**Shot Event Properties:**
- `x`, `y`: Calibrated arena coordinates
- `raw_x`, `raw_y`: Raw camera coordinates (optional)
- `color`: Laser color (optional)
- `confidence`: Detection confidence 0-1 (optional)
- `timestamp`: Event timestamp

### Listen Only to Calibration Status
Perfect for calibration UI:
```typescript
this.shootOffService.connectToCalibration({ calibrate: true }).subscribe({
  next: (status) => {
    if (status.status === 'manual_adjusting') {
      console.log('Drag the bbox in the backend preview window, then press Enter.');
    } else if (status.status === 'calibrated') {
      console.log(`Calibrated! BBox: ${status.bbox}, Confidence: ${status.confidence}`);
    } else if (status.status === 'calibration_failed') {
      console.log(`Failed: ${status.reason}`);
    }
  },
});
```

**Calibration Status Properties:**
- `status`: 'manual_adjusting' | 'calibrated' | 'calibration_failed'
- `bbox`: [left, top, right, bottom] calibration area (optional)
- `mode`: 'manual' | 'cached' (optional)
- `confidence`: 0-1 confidence score (optional)
- `elapsed_seconds`: Time spent in the calibration flow (optional)
- `reason`: Failure reason (optional)

### Listen Only to Errors
```typescript
this.shootOffService.connectToErrors().subscribe({
  next: (error) => {
    console.error('ShootOFF Error:', error.error);
  },
});
```

## Connection State Monitoring

Track connection status in real-time:
```typescript
export class MyComponent {
  connectionState$ = this.shootOffService.connectionState;
  lastError$ = this.shootOffService.lastError;

  constructor(private shootOffService: ShootOffSocketService) {}

  // In template:
  // <div [ngSwitch]="connectionState$()">
  //   <span *ngSwitchCase="'connected'">✓ Connected</span>
  //   <span *ngSwitchCase="'connecting'">⟳ Connecting...</span>
  //   <span *ngSwitchCase="'error'">✗ Error: {{ lastError$() }}</span>
  // </div>
}
```

## Type Guards

Use type guards to safely handle different message types:
```typescript
this.shootOffService.connect().subscribe({
  next: (message) => {
    if (this.shootOffService.isShotEvent(message)) {
      // message is ShootOffShotEvent
      console.log('Shot:', message.x, message.y);
    } else if (this.shootOffService.isCalibrationStatus(message)) {
      // message is ShootOffCalibrationStatus
      console.log('Calibration:', message.status);
    } else if (this.shootOffService.isErrorMessage(message)) {
      // message is ShootOffErrorMessage
      console.log('Error:', message.error);
    }
  },
});
```

## Options

Both `connect()` and filtered methods support options:

```typescript
interface ShootOffSocketOptions {
  debugPreview?: boolean;  // Enable debug preview in Python backend
  calibrate?: boolean;     // Force re-calibration
}
```

Example:
```typescript
// Force recalibration with debug preview
this.shootOffService.connectToCalibration({ 
  calibrate: true, 
  debugPreview: true 
}).subscribe(/* ... */);
```

## Real-World Example: Game Component

```typescript
import { Component, inject, signal, OnInit } from '@angular/core';
import { ShootOffSocketService } from './shootoff-socket.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-shooting-game',
  template: `
    <div class="game-container">
      <div class="status">
        <span [ngSwitch]="connectionState()">
          <span *ngSwitchCase="'connected'" class="connected">✓ Ready</span>
          <span *ngSwitchCase="'connecting'" class="connecting">Calibrating...</span>
          <span *ngSwitchCase="'error'" class="error">Error: {{ lastError() }}</span>
        </span>
      </div>
      <div class="score">Shots: {{ shots() }} | Hits: {{ hits() }}</div>
    </div>
  `,
})
export class ShootingGameComponent implements OnInit {
  private shootOffService = inject(ShootOffSocketService);

  protected shots = signal(0);
  protected hits = signal(0);
  protected connectionState = this.shootOffService.connectionState;
  protected lastError = this.shootOffService.lastError;

  private shotSubscription?: Subscription;
  private calibrationSubscription?: Subscription;

  ngOnInit() {
    this.startCalibration();
  }

  private startCalibration() {
    this.calibrationSubscription = this.shootOffService
      .connectToCalibration({ calibrate: true })
      .subscribe({
        next: (status) => {
          if (status.status === 'manual_adjusting') {
            console.log('Manual calibration is active, waiting for Enter...');
          } else if (status.status === 'calibrated') {
            console.log('Calibration successful, starting game...');
            this.startGame();
          } else if (status.status === 'calibration_failed') {
            console.error('Calibration failed:', status.reason);
          }
        },
        error: (err) => console.error('Calibration error:', err),
      });
  }

  private startGame() {
    this.calibrationSubscription?.unsubscribe();

    this.shotSubscription = this.shootOffService.connectToShots().subscribe({
      next: (shot) => {
        this.shots.update((s) => s + 1);
        
        // Check if shot hit a target (simplified)
        if (this.isHit(shot.x, shot.y)) {
          this.hits.update((h) => h + 1);
        }

        console.log(
          `Shot: (${shot.x.toFixed(0)}, ${shot.y.toFixed(0)}) ` +
          `Confidence: ${shot.confidence?.toFixed(2)}`
        );
      },
      error: (err) => console.error('Shot stream error:', err),
    });
  }

  private isHit(x: number, y: number): boolean {
    // Your hit detection logic
    return true;
  }

  ngOnDestroy() {
    this.shotSubscription?.unsubscribe();
    this.calibrationSubscription?.unsubscribe();
  }
}
```

## Error Handling

The service automatically tracks connection state and errors:

```typescript
export class ErrorHandlingComponent implements OnInit {
  private shootOffService = inject(ShootOffSocketService);
  connectionState$ = this.shootOffService.connectionState;
  lastError$ = this.shootOffService.lastError;

  ngOnInit() {
    effect(() => {
      const state = this.connectionState$();
      if (state === 'error') {
        console.error('Connection lost:', this.lastError$());
        // Implement retry logic or user notification
      }
    });
  }
}
```

## Integration with Python api.py

The service automatically:
1. Resolves the correct WebSocket URL (`wss://` for HTTPS, `ws://` for HTTP)
2. Uses the correct path `/api/ws/shots` defined in `api.py`
3. Properly parses all message types from the backend
4. Handles connection lifecycle (open, close, error, timeout)

The Python backend (`api.py`) provides:
- **Calibration**: Manual or cached projector calibration
- **Shot Detection**: Java shot detector integration with configurable parameters
- **Frame Processing**: Real-time video frame processing with ROI masking
- **Arena Mapping**: Calibrated shot coordinates mapped to virtual arena (800x600)

## Performance Tips

1. **Use Filtered Streams**: Instead of filtering in subscribe, use `connectToShots()`, `connectToCalibration()`, etc.
   ```typescript
   // ✓ Good
   this.shootOffService.connectToShots().subscribe(/* ... */);
   
   // ✗ Less optimal
   this.shootOffService.connect().pipe(
     filter(msg => this.shootOffService.isShotEvent(msg))
   ).subscribe(/* ... */);
   ```

2. **Manage Subscriptions**: Always unsubscribe to prevent memory leaks
   ```typescript
   subscription?.unsubscribe();
   // or use takeUntilDestroyed() in standalone components
   ```

3. **Monitor Connection State**: Use signals to track connection health
   ```typescript
   effect(() => {
     if (this.connectionState$() === 'error') {
       // Handle errors gracefully
     }
   });
   ```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No shots received | Check Python backend is running and `calibrate: true` first |
| Connection times out | Verify backend URL and network connectivity |
| Calibration fails | Ensure camera/projector setup matches Python backend config |
| Wrong coordinates | Verify arena dimensions (default: 800x600) match your game |

For Python backend configuration, see `ShootOFF-legacy-master/api.py`.
