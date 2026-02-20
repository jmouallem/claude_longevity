const SPECIALIST_COLORS: Record<string, string> = {
  nutritionist: 'bg-green-500/20 text-green-400 border-green-500/30',
  sleep_expert: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  movement_coach: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  supplement_auditor: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  safety_clinician: 'bg-red-500/20 text-red-400 border-red-500/30',
  orchestrator: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
};

const DEFAULT_COLORS = 'bg-slate-500/20 text-slate-400 border-slate-500/30';
const SPECIALIST_DISPLAY_NAMES: Record<string, string> = {
  orchestrator: 'Longevity Coach',
};

function formatName(specialist: string): string {
  if (SPECIALIST_DISPLAY_NAMES[specialist]) {
    return SPECIALIST_DISPLAY_NAMES[specialist];
  }

  return specialist
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

interface SpecialistBadgeProps {
  specialist: string;
}

export default function SpecialistBadge({ specialist }: SpecialistBadgeProps) {
  const colors = SPECIALIST_COLORS[specialist] || DEFAULT_COLORS;

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${colors}`}
    >
      {formatName(specialist)}
    </span>
  );
}
