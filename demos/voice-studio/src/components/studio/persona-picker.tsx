import type { CSSProperties } from "react";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { PERSONAS } from "@/lib/personas";
import PersonaAvatar from "./persona-avatar";

/** 01 / CHOOSE YOUR PERSONA */
export default function PersonaPicker({
  selected,
  active,
  onChoose,
}: {
  selected: string;
  active: boolean;
  onChoose: (value: string) => void;
}) {
  return (
    <section className="persona-section" aria-labelledby="persona-heading">
      <div className="workspace-heading">
        <div>
          <span className="eyebrow">01 / CHOOSE YOUR PERSONA</span>
          <h1 id="persona-heading">Who will you talk to?</h1>
        </div>
        <p>Pick an Indian persona and converse natively in Hindi or Indian regional languages with Gemini Live or Cascade.</p>
      </div>
      <RadioGroup
        aria-labelledby="persona-heading"
        value={selected}
        onValueChange={onChoose}
        className="persona-grid"
        disabled={active}
      >
        {PERSONAS.map((item) => {
          const isSelected = selected === item.id;
          return (
            <label
              key={item.id}
              htmlFor={item.id}
              className={`persona-card ${item.id === "custom" ? "custom-card" : ""} ${isSelected ? "selected" : ""} ${
                active ? "locked" : ""
              }`}
              style={{ "--card-color": item.color } as CSSProperties}
            >
              <div className="persona-card-top">
                <PersonaAvatar key={item.id} persona={item} className="card-portrait" />
                <RadioGroupItem
                  id={item.id}
                  value={item.id}
                  aria-label={item.id === "custom" ? item.name : `${item.agentName}, ${item.name}`}
                />
              </div>
              <strong>{item.id === "custom" ? item.name : item.agentName}</strong>
              {item.id !== "custom" && <span className="persona-role">{item.name}</span>}
              <span className="persona-description">{item.description}</span>
              {isSelected && !active && (
                <div className="card-quick-actions">
                  <span className="card-active-pill">Selected</span>
                </div>
              )}
            </label>
          );
        })}
      </RadioGroup>
    </section>
  );
}
