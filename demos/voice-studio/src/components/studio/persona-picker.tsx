import type { CSSProperties } from "react";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { PERSONAS } from "@/lib/personas";
import PersonaAvatar from "./persona-avatar";

/** 01 / CHOOSE YOUR PERSONA (Scrollable Left Sidebar Pane) */
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
    <div className="persona-sidebar-container" aria-labelledby="persona-heading">
      <div className="sidebar-header">
        <div className="sidebar-badge-row">
          <span className="eyebrow">01 / PERSONAS</span>
          <span className="persona-count-badge">{PERSONAS.length} AGENTS</span>
        </div>
        <h2 id="persona-heading" className="sidebar-heading">Who will you talk to?</h2>
        <p className="sidebar-subtitle">Select an Indian persona to converse natively.</p>
      </div>

      <div className="persona-scroll-pane">
        <RadioGroup
          aria-labelledby="persona-heading"
          value={selected}
          onValueChange={onChoose}
          className="persona-list"
          disabled={active}
        >
          {PERSONAS.map((item) => {
            const isSelected = selected === item.id;
            return (
              <label
                key={item.id}
                htmlFor={item.id}
                className={`persona-card persona-sidebar-card ${item.id === "custom" ? "custom-card" : ""} ${
                  isSelected ? "selected" : ""
                } ${active ? "locked" : ""}`}
                style={{ "--card-color": item.color } as CSSProperties}
              >
                <div className="persona-card-row">
                  <div className="persona-avatar-wrap">
                    <PersonaAvatar key={item.id} persona={item} className="card-portrait" />
                    {isSelected && <span className="avatar-active-dot" />}
                  </div>
                  <div className="persona-info-wrap">
                    <div className="persona-name-row">
                      <strong className="agent-display-name">
                        {item.id === "custom" ? item.name : item.agentName}
                      </strong>
                      <RadioGroupItem
                        id={item.id}
                        value={item.id}
                        aria-label={item.id === "custom" ? item.name : `${item.agentName}, ${item.name}`}
                      />
                    </div>
                    {item.id !== "custom" && <span className="persona-role persona-role-chip">{item.name}</span>}
                    <p className="persona-description">{item.description}</p>
                    {isSelected && !active && (
                      <div className="card-quick-actions">
                        <span className="card-active-pill">Selected</span>
                      </div>
                    )}
                  </div>
                </div>
              </label>
            );
          })}
        </RadioGroup>
      </div>
    </div>
  );
}
