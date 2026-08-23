"""Order extraction prompt (plan §25).

v2 halves v1's length. What was cut was cut because the schema already says
it: two of the four worked examples demonstrated nothing beyond "fill the
obvious fields", the "return only schema fields" rule is enforced by
`extra="ignore"` and by strict decoding, and the priority instructions went
with the `ai_priority` field.

What survives is load-bearing and asserted by `test_output_schema.py`:

* never invent -- the anti-hallucination rule the regression suite checks on
  29 separate null expectations
* never estimate -- estimates are arithmetic in `estimator.py`
* quote the source exactly -- `spans.py` needs a verbatim substring to resolve
  into the character offsets the review UI highlights
* vague wording stays null

The two remaining examples are the only evidence of two rules: the mm/one-week
case is the sole demonstration of "quote the source, not the converted value",
and the "khoảng vài trăm" case makes the null rule concrete.

No hidden reasoning is requested, and no character offsets: counting
characters is what models are worst at, so `spans.py` does it.
"""

from __future__ import annotations

from app.prompts.versions import PromptVersion

_INSTRUCTIONS = """\
Extract structured order data from a Vietnamese ceramics order description.

Rules
1. Extract only what the text states. Never invent. Not stated -> null.
2. Never estimate. No stated temperature -> firing_temperature_c = null.
3. Normalise only when unambiguous: lengths -> cm (40mm->4, 1.2m->120);
   temperature -> whole degrees C (1.280°C->1280, "1280 do"->1280);
   deadlines -> days (một tuần->7, nửa tháng->15, 2 tuần->14).
4. Vague amounts ("khoảng vài trăm", "một ít") and vague deadlines
   ("càng sớm càng tốt") -> null. A null is correct; a guess is not.
5. width_cm also carries "đường kính" (diameter).
6. evidence: for each field you filled, copy the EXACT substring of the
   description supporting it -- character for character, diacritics included.
   Never paraphrase, translate, or add characters. Quote the source, not the
   converted value ("cao 40mm", not "4"). Leave evidence null where the field
   is null.
7. Keep product names, patterns and glazes in the customer's Vietnamese,
   lightly tidied ("dia gom" -> "Đĩa gốm").

Examples
"Cần 60 chén gốm men trắng, cao 40mm, giao trong một tuần."
-> quantity=60, product_name="Chén gốm", glaze_type="Men trắng", height_cm=4,
   deadline_days=7, rest null.
   evidence: quantity="60", product_name="chén gốm", glaze_type="men trắng",
   height_cm="cao 40mm", deadline_days="trong một tuần".

"Làm khoảng vài trăm cái, càng sớm càng tốt."
-> every field null. Do not write 200, 300, or 1.
"""

ORDER_EXTRACTION_V2 = PromptVersion(
    name="order-extraction-v2",
    instructions=_INSTRUCTIONS,
)
