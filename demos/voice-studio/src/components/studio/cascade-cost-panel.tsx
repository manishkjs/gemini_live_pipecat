import { formatCost } from "@/lib/pricing";
import { formatCacheHit, stageLabel, type CascadeCost } from "@/lib/cascade-cost";

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
          const cacheHit = formatCacheHit(row);
          return <span key={stage} title={row?.issues.join(" · ") || undefined}>
            {stage.toUpperCase()} {stageLabel(row)}{cacheHit ? ` (${cacheHit})` : ""}
          </span>;
        })}
      </span>
    </summary>
    <p>Public USD rate estimate from provider usage_metadata received so far. A partial amount is the known subtotal, not the full call cost. LLM input cost applies the reported cache hit rate (cached_content_token_count at the cached rate, remaining input at the standard rate), and LLM output includes thinking tokens. When Skip STT is enabled, STT is off ($0). Excludes credits, free tiers, volume discounts, taxes and hosting.</p>
    {cost?.stages.map(stage => <div className="cascade-cost-stage" key={stage.stage}>
      <strong>{stage.stage.toUpperCase()}</strong>
      <span>
        {stage.disabled ? "Disabled for this call ($0)" : `${stage.requests} provider requests`}
        {stage.estimated ? " · estimated from streamed audio (25 tokens/s); provider returns no usage" : ""}
        {stage.stage === "llm" && (stage.prompt_tokens ?? 0) > 0
          ? ` · ${(stage.prompt_tokens ?? 0).toLocaleString()} input tokens (${(stage.cached_tokens ?? 0).toLocaleString()} cached · ${(((stage.cache_hit_rate ?? 0) * 100)).toFixed(1)}% cache hit, ${(stage.uncached_prompt_tokens ?? 0).toLocaleString()} uncached) · ${(stage.output_tokens ?? 0).toLocaleString()} output tokens`
          : ""}
      </span>
      {stage.issues.length > 0 && <p>{stage.issues.join(" · ")}</p>}
      {stage.rates.map((rate, i) => <div key={i}>
        <span>{rate.model} · {rate.provider} · {rate.region}</span>
        <ul>{Object.entries(rateLabels).filter(([key]) => rate[key] != null).map(([key, label]) =>
          <li key={key}>${rate[key]} / {label}</li>)}</ul>
        {(rate.source?.startsWith("https://cloud.google.com/") || rate.source?.startsWith("https://docs.cloud.google.com/") || rate.source?.startsWith("https://ai.google.dev/")) &&
          <a href={rate.source} target="_blank" rel="noreferrer">Google pricing source</a>}
      </div>)}
    </div>)}
    <p>Rates checked {cost?.reviewed_at ?? "2026-10-29"}. Gemini 3.7 and 3.8 introductory rates end December 31, 2026. Cloud Billing remains authoritative for invoiced spend.</p>
  </details>;
}

