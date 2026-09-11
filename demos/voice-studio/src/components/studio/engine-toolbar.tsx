import { Layers3, Radio, Globe2 } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LANGUAGE_OPTIONS, type SessionSettings } from "@/lib/voice-session";

/** 02 / CHOOSE YOUR ENGINE and 03 / LANGUAGE */
export default function EngineToolbar({
  settings,
  active,
  onEngineChange,
  onLanguageChange,
}: {
  settings: SessionSettings;
  active: boolean;
  onEngineChange: (value: string) => void;
  onLanguageChange: (value: string) => void;
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

      <div className="language-choice">
        <span className="eyebrow">LANGUAGE</span>
        <Select
          value={settings.language}
          onValueChange={onLanguageChange}
          disabled={active}
        >
          <SelectTrigger className="language-select-trigger" aria-label="Select session language">
            <Globe2 size={14} />
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            {LANGUAGE_OPTIONS.map(([v, l]) => (
              <SelectItem value={v} key={v}>
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
