import { useState } from "react";
import { BookOpen, Coffee, Heart, SlidersHorizontal, Wallet } from "lucide-react";
import type { Persona } from "@/lib/personas";

const icons = {
  "debt-collector": Wallet,
  "reservation-agent": Coffee,
  storyteller: BookOpen,
  "ai-companion": Heart,
  custom: SlidersHorizontal,
};

export default function PersonaAvatar({ persona, className = "" }: { persona: Persona; className?: string }) {
  const [failed, setFailed] = useState(false);
  const Icon = icons[persona.id];
  return (
    <span className={`persona-avatar ${className}`}>
      {persona.portrait && !failed ? (
        <img
          src={persona.portrait}
          alt={`AI-generated portrait of ${persona.agentName}`}
          width={128}
          height={128}
          decoding="async"
          onError={() => setFailed(true)}
        />
      ) : (
        <Icon size={22} aria-hidden="true" />
      )}
    </span>
  );
}
