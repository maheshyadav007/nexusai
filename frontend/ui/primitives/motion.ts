import light from "@/ui/theme/themes/nexus-light.json";

const seconds = (value: string) => Number.parseFloat(value) / 1000;
const curve = (value: string) => (value.match(/-?[\d.]+/g) ?? []).map(Number) as [number, number, number, number];

/** The theme's motion values, in the form Motion takes. Motion can't read CSS variables here. */
export const EASE = curve(light.motion.easing);
export const QUICK = { duration: seconds(light.motion.fast), ease: EASE };
export const SMOOTH = { duration: seconds(light.motion.normal), ease: EASE };

export const FADE_RISE = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 8 },
  transition: SMOOTH,
};

/** For a card that grows from where it was opened. */
export const PANEL = {
  initial: { opacity: 0, y: 12, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: 12, scale: 0.98 },
  transition: SMOOTH,
};

export const REVEAL = {
  initial: { height: 0, opacity: 0 },
  animate: { height: "auto", opacity: 1 },
  exit: { height: 0, opacity: 0 },
  transition: SMOOTH,
};
