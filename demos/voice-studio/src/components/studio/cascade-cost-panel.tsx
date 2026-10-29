import { formatCost } from "@/lib/pricing";
import { stageLabel, type CascadeCost } from "@/lib/cascade-cost";

const rateLabels: Record<string, string> = {
  text_in: "text input / 1M tokens", audio_in: "audio input / 1M tokens",
  text_out: "text output / 1M tokens", audio_out: "audio output / 1M tokens",
  cached_text_in: "cached text / 1M tokens", cached_audio_in: "cached audio / 1M tokens",
  characters: "1M characters", audio_minute: "audio minute (first tier)",
};

export default function CascadeCostPanel({ cost }: { cost: CascadeCost | null }) {
  return <details className="cascade-cost-panel">
    <summary>
      <span>Cascade API cost · USD</span>
      <strong>{cost ? `${formatCost(Number(cost.known_usd))}${cost.complete ? "" : " · partial"}` : "Awaiting usage"}</strong>
      <span className="cascade-cost-stages">
        {(["stt", "llm", "tts"] as const).map(stage => {
          const row = cost?.stages.find(s => s.stage === stage);
          return <span key={stage} title={row?.issues.join(" · ") || undefined}>{stage.toUpperCase()} {stageLabel(row)}</span>;
        })}
      </span>
    </summary>
    <p>Public USD rate estimate for API usage received so far. A partial amount is the known subtotal, not the full call cost. LLM output includes thinking. STT includes background transcription when audio goes directly to the LLM. Excludes credits, free tiers, volume discounts, taxes and hosting.</p>
    {cost?.stages.map(stage => <div className="cascade-cost-stage" key={stage.stage}>
      <strong>{stage.stage.toUpperCase()}</strong>
      <span>{stage.disabled ? "Disabled for this call" : `${stage.requests} provider requests`}{stage.estimated ? " · estimated from streamed audio (25 tokens/s); provider returns no usage" : ""}</span>
      {stage.issues.length > 0 && <p>{stage.issues.join(" · ")}</p>}
      {stage.rates.map((rate, i) => <div key={i}>
        <span>{rate.model} · {rate.provider} · {rate.region}</span>
        <ul>{Object.entries(rateLabels).filter(([key]) => rate[key] != null).map(([key, label]) =>
          <li key={key}>${rate[key]} / {label}</li>)}</ul>
        {(rate.source?.startsWith("https://cloud.google.com/") || rate.source?.startsWith("https://ai.google.dev/")) &&
          <a href={rate.source} target="_blank" rel="noreferrer">Google pricing source</a>}
      </div>)}
    </div>)}
    <p>Rates checked {cost?.reviewed_at ?? "2026-09-13"}. Gemini 3.7 introductory rates end December 31, 2026. Cloud Billing remains authoritative for invoiced spend.</p>
  </details>;
}
