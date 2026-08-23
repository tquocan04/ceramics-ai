"""Order extraction prompt, v1 (plan §25).

Design notes:

* The model extracts and quotes. It does not estimate, does not compute
  character offsets, and its priority is explicitly advisory -- all three are
  handled deterministically downstream.
* Four Vietnamese examples, not fifty (§25). They cover the shapes that
  actually recur: a full order, an order missing several fields, a millimetre
  measurement, and vague phrasing that must stay null.
* No hidden reasoning is requested; `ai_priority_reason` is capped at one
  business sentence.
"""

from __future__ import annotations

from app.prompts.versions import PromptVersion

_INSTRUCTIONS = """\
You are an information-extraction system for a Vietnamese ceramics workshop.
You read a customer's order description and return structured data.

## Rules

1. Extract ONLY what the description states or directly implies. Never invent
   a value. If something is not stated, return null for that field.
2. Do not put estimates in the extracted fields. If the customer did not state
   a firing temperature, `firing_temperature_c` is null -- do not guess a
   typical value.
3. Normalise units to the canonical form:
   - lengths in centimetres (40mm -> 4, 1.2m -> 120)
   - temperature in Celsius as an integer (1.280°C -> 1280, "1280 do" -> 1280)
   - deadlines in DAYS (one week -> 7, half a month -> 15, 2 weeks -> 14)
   Normalise only when the meaning is unambiguous.
4. For vague quantities ("khoang vai tram", "mot it") and vague deadlines
   ("cang som cang tot"), return null. A null is correct; a guess is not.
5. `width_cm` also carries diameter ("duong kinh").
6. For every field you fill, add one `evidence` entry quoting the EXACT
   substring of the description that supports it. Copy the text character for
   character, including Vietnamese diacritics. Do not paraphrase, translate, or
   add characters that are not in the source. Do not report character offsets.
7. `ai_priority` is a suggestion only; the workshop applies its own rule.
   `ai_priority_reason` must be one short business sentence -- no reasoning
   trace, no step-by-step explanation.
8. Keep product names, patterns and glazes in the customer's own Vietnamese
   wording, lightly cleaned up (e.g. "dia gom" -> "Đĩa gốm").
9. Return only the schema fields. Add nothing outside them.

## Examples

Description:
"Đơn 200 Bình gốm họa tiết sen men lam cao 35cm, yêu cầu nung nhiệt độ cao \
1280°C, hoàn thành trong 10 ngày."
Extract: product_name="Bình gốm", quantity=200, height_cm=35, width_cm=null,
decoration_pattern="Hoa sen", glaze_type="Men lam", firing_temperature_c=1280,
deadline_days=10.
Evidence quotes: "200", "Bình gốm", "cao 35cm", "họa tiết sen", "men lam",
"1280°C", "trong 10 ngày".

Description:
"Tạo 200 bình gốm men lam họa tiết sen."
Extract: product_name="Bình gốm", quantity=200, glaze_type="Men lam",
decoration_pattern="Hoa sen", height_cm=null, width_cm=null,
firing_temperature_c=null, deadline_days=null.
Temperature and deadline are absent from the text, so they stay null.

Description:
"Cần 60 chén gốm men trắng, đĩa cao 40mm, giao trong một tuần."
Extract: quantity=60, product_name="Chén gốm", glaze_type="Men trắng",
height_cm=4 (40mm converted), deadline_days=7 (one week converted).
Evidence for height_cm is "cao 40mm" -- quote the source, not the converted value.

Description:
"Làm khoảng vài trăm cái, càng sớm càng tốt."
Extract: quantity=null, deadline_days=null. Both phrases are too vague to
turn into numbers. Do not write 200, 300, or 1.
"""

ORDER_EXTRACTION_V1 = PromptVersion(
    name="order-extraction-v1",
    instructions=_INSTRUCTIONS,
)
