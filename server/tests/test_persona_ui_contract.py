"""Exercise real UI exports against the backend; no second list of demo personas."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from persona_identity import normalize_persona_id
from persona_registry import PERSONA_REGISTRY, is_persona_ui_editable
from persona_prompt_cards import get_persona_all_cards, get_persona_card, get_session_preset


class TestPersonaUIContract(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Cross-stack contract requires Node.js 22.13+ (Voice Studio prerequisite)")
    def test_visible_ids_editor_locks_and_journey_phases_match_the_backend(self):
        repo = Path(__file__).resolve().parents[2]
        module = (repo / "demos/voice-studio/src/lib/personas.ts").as_uri()
        script = f"""
import {{ PERSONAS }} from {json.dumps(module)};
console.log(JSON.stringify(PERSONAS.map(p => ({{
    id: p.id, locked: !!p.architectureLocked, phases: p.phaseIds || []
}}))));
"""
        result = subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", script],
                                capture_output=True, text=True, check=True, timeout=15)
        personas = json.loads(result.stdout)
        self.assertTrue(personas)
        self.assertEqual(len(personas), len({p["id"] for p in personas}))
        for persona in personas:
            with self.subTest(persona=persona["id"]):
                persona_id = persona["id"]
                self.assertIn(persona_id, PERSONA_REGISTRY)
                self.assertEqual(persona["locked"], not is_persona_ui_editable(persona_id))
                for engine in ("live", "cascade"):
                    preset = get_session_preset(persona_id, engine=engine)
                    if persona_id == "custom":
                        self.assertIsNone(preset)
                    else:
                        self.assertTrue(preset)
                resolved = set()
                for index, phase_id in enumerate(persona["phases"]):
                    # Pragya's opening lives in the root prompt. Her other three
                    # phases, and all four Ananya/Kavya phases, are actual cards.
                    if (normalize_persona_id(persona_id), phase_id) == ("lamborghini-concierge", "SOP_01_OPENING"):
                        self.assertEqual(index, 0)
                        continue
                    card = get_persona_card(persona_id, phase_id)
                    self.assertIsNotNone(card, f"UI phase {phase_id} has no backend card")
                    resolved.add(card.phase_id)
                self.assertEqual(resolved, {card.phase_id for card in get_persona_all_cards(persona_id).values()})
