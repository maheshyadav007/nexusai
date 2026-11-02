"use client";

// Two soft notes, generated so no audio file ships with the app. Browsers only allow sound after
// someone has interacted with the page, and that failing quietly is fine.
const NOTES = [
  { hz: 660, at: 0 },
  { hz: 880, at: 0.11 },
];
const NOTE_SECONDS = 0.16;
const LOUDNESS = 0.05;

let shared: AudioContext | null = null;

export function playChime(): void {
  try {
    shared ??= new AudioContext();
    void shared.resume();
    const start = shared.currentTime;
    for (const note of NOTES) {
      const tone = shared.createOscillator();
      const volume = shared.createGain();
      tone.type = "sine";
      tone.frequency.value = note.hz;
      volume.gain.setValueAtTime(LOUDNESS, start + note.at);
      volume.gain.exponentialRampToValueAtTime(0.0001, start + note.at + NOTE_SECONDS);
      tone.connect(volume).connect(shared.destination);
      tone.start(start + note.at);
      tone.stop(start + note.at + NOTE_SECONDS);
    }
  } catch {
    // No audio on this machine. Nothing else depends on it.
  }
}
