import { Sprite, Texture } from 'pixi.js';

export class BulletMark {
  readonly sprite: Sprite;

  constructor(texture: Texture, localX: number, localY: number, displayDiameter: number) {
    this.sprite = new Sprite(texture);
    this.sprite.anchor.set(0.5);
    this.sprite.position.set(localX, localY);
    this.sprite.rotation = Math.random() * Math.PI * 2;

    const baseDiameter = Math.max(texture.width, texture.height, 1);
    const scale = displayDiameter / baseDiameter;
    this.sprite.scale.set(scale);
  }

  update(deltaMs: number): boolean {
    void deltaMs;
    return false;
  }

  destroy(): void {
    this.sprite.destroy();
  }
}
