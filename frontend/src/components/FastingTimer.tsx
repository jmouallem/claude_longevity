import { useFastingTimer } from '../hooks/useFastingTimer';

export default function FastingTimer() {
  const { isActive, elapsedFormatted, fastType } = useFastingTimer();

  if (!isActive) {
    return (
      <div className="text-center">
        <p className="text-slate-500 text-sm font-medium">Not fasting</p>
      </div>
    );
  }

  return (
    <div className="text-center">
      <div className="relative inline-block">
        <div className="absolute -inset-3 rounded-full bg-emerald-500/20 animate-pulse" />
        <p className="relative text-4xl font-mono font-bold text-emerald-400 tracking-wider">
          {elapsedFormatted}
        </p>
      </div>
      <p className="text-emerald-400 text-sm font-medium mt-3">Fasting</p>
      {fastType && (
        <p className="text-slate-400 text-xs mt-1">{fastType}</p>
      )}
    </div>
  );
}
