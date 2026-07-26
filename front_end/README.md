# Laser Simulation Frontend

Interactive browser shooting-range simulation built with Angular and PixiJS.

## Overview

This project combines:

- Angular 21 (standalone app shell and HUD)
- PixiJS 8 (2D rendering, targets, interactions, effects)
- Multi-level game flow with objectives, difficulty control, and post-level performance reports

The game currently has configured content for levels 1 to 6, with level slots 7 to 10 reserved but empty.

## Features

- Level selector with per-level objective handling
- Three difficulty profiles (`Easy`, `Medium`, `Hard`)
- Start and restart session controls
- Real-time HUD metrics: score, hits, accuracy, last points, timer
- Floating score popups and bullet impact marks
- Ally-protection failure logic on specific levels
- Level completion report with analytics:
	- elapsed time
	- accuracy
	- misses
	- points per shot
	- hits per minute

## Tech Stack

- Angular `^21.2.0`
- Angular CLI `^21.2.6`
- PixiJS `^8.17.1`
- TypeScript `~5.9.2`
- Vitest `^4.0.8`

## Project Structure

```text
laser-simulation-frontend/
|- public/assets/shooting-range/   # Images, models, and sounds
|- src/
|  |- app/
|  |  |- app.ts                     # Angular app shell, level/session logic, HUD state
|  |  |- app.html                   # HUD and controls layout
|  |  |- app.scss                   # UI styling
|  |  \- shooting-range/
|  |     |- game.ts                 # Pixi app, entities, level mechanics
|  |     |- target.ts               # Target movement and hit scoring zones
|  |     |- score.ts                # Floating score text effect
|  |     |- bullet.ts               # Bullet mark sprite wrapper
|  |     \- laser_detection.ipynb   # Notebook used for experimentation
|  |- main.ts                       # Angular bootstrap entry
|  \- styles.scss                   # Global styles
|- angular.json
|- package.json
\- README.md
```

## Prerequisites

- Node.js 20+
- npm 10+

## Setup

```bash
npm install
```

## Run Locally

```bash
npm start
```

Then open:

```text
http://localhost:4200/
```

## Scripts

- `npm start` - start the Angular dev server
- `npm run build` - production build
- `npm run watch` - development build in watch mode
- `npm test` - run unit tests (Vitest via Angular builder)

## Controls

- Click `Start` to begin a level session
- Click `Restart` to reset timer, score, and current level state
- Use `Levels` menu to switch levels
- Use difficulty buttons (`Easy`, `Medium`, `Hard`) to tune speed/size behavior
- Left mouse click on the stage to shoot
- For levels 1 and 2, target score can be edited while session is not running

## Level Objectives (Current)

- Level 1: score objective (default target score `180`, editable)
- Level 2: score objective (default target score `220`, editable)
- Level 3: clear waves 1 to 4
- Level 4: clear waves 1 to 4
- Level 5: score objective (target score `200`)
- Level 6: randomized terrorist/innocent encounters with +/- scoring
- Levels 7 to 10: reserved, currently empty

## Scoring Rules

- Target zones award points by ring and body area:
	- Head zone: `50`, `70`, `100`
	- Chest zone: `10`, `25`, `50`
- Shooting an innocent in ally-protection levels triggers a penalty and session stop
- Level 6 encounters:
	- terrorist hit: `+50`
	- innocent hit: `-50`

## Notes

- Audio files are loaded from `public/assets/shooting-range/sounds`.
- Level/background assets are loaded from `public/assets/shooting-range`.
- If some background assets are missing, fallback drawing logic is used for certain scenes.

## Testing

Run:

```bash
npm test
```

Current tests are minimal and can be expanded with gameplay logic tests around scoring, level completion, and failure conditions.

## Future Improvements

- Implement gameplay content for levels 7 to 10
- Add end-to-end tests for session flow and objective completion
- Add persistent profile/progression tracking
- Provide balancing config via JSON for easier tuning
