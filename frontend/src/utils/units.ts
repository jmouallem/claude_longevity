export type WeightUnit = 'kg' | 'lb';
export type HeightUnit = 'cm' | 'ft';
export type HydrationUnit = 'ml' | 'oz';

const KG_PER_LB = 0.45359237;
const ML_PER_FL_OZ = 29.5735295625;

export function lbToKg(lb: number): number {
  return lb * KG_PER_LB;
}

export function kgToLb(kg: number): number {
  return kg / KG_PER_LB;
}

export function ftInToCm(ft: number, inches: number): number {
  return ft * 30.48 + inches * 2.54;
}

export function cmToFtIn(cm: number): [number, number] {
  const totalInches = cm / 2.54;
  const ft = Math.floor(totalInches / 12);
  let inches = Math.round(totalInches - ft * 12);
  if (inches === 12) {
    inches = 0;
    return [ft + 1, inches];
  }
  return [ft, inches];
}

export function mlToOz(ml: number): number {
  return ml / ML_PER_FL_OZ;
}

export function ozToMl(oz: number): number {
  return oz * ML_PER_FL_OZ;
}

export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}
