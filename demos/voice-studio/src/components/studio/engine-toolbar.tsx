import { Layers3, Radio } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { SessionSettings } from "@/lib/voice-session";

/** Engine selection. Language lives in Settings -- one control, one home. */
export default function EngineToolbar({
  settings,
  active,
  onEngineChange,
}: {
  settings: SessionSettings;
  active: boolean;
  onEngineChange: (value: string) => void;
}) {
  return (
    <div className="workspace-toolbar">
      <div className="engine-choice">
        <span className="eyebrow">ENGINE</span>
        <Tabs value={settings.engine} onValueChange={onEngineChange}>
          <TabsList aria-label="Voice engine" className="engine-tabs">
            <TabsTrigger value="live" disabled={active}>
              <Radio size={14} />Gemini Live
            </TabsTrigger>
            <TabsTrigger value="cascade" disabled={active}>
              <Layers3 size={14} />Cascade
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
    </div>
  );
}
