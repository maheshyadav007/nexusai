import light from "@/ui/theme/themes/nexus-light.json";

const seconds = (value: string) => Number.parseFloat(value) / 1000;
const curve = (value: string) => (value.match(/-?[\d.]+/g) ?? []).map(Number) as [number, number, number, number];

/** A theme size in pixels, for motion and measuring, which can't use CSS variables. */
export const readSpace = (value: string) => Number.parseFloat(value);

/** The theme's motion values, in the form Motion takes. Motion can't read CSS variables here. */
export const EASE = curve(light.motion.easing);
export const QUICK = { duration: seconds(light.motion.fast), ease: EASE };
export const SMOOTH = { duration: seconds(light.motion.normal), ease: EASE };
export const SLOW = { duration: seconds(light.motion.slow), ease: EASE };
