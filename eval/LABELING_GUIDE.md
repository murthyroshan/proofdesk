# ProofDesk — Labeling Guide (for teammates, ~1.5 h)

**Goal:** create the "answer key" we test the AI against. Two people label the SAME items **independently**
(don't discuss until both are done). We then measure how often you agree, and a faculty member settles disagreements.

**Rules**
- Label only what you can SEE in the document. Don't guess.
- These are public files, but do not share or post them anywhere. Internal testing only.
- If a page shows personal data (phone numbers, Aadhaar, ID cards), mark `pii = yes` and skip judging it.

---

## For each item, fill one row in `labels_<yourname>.csv`

| Column | What to write |
|---|---|
| `item_id` | Given in the sheet (e.g. `3.6.3_1_p4-5`) |
| `metric` | Given (the metric we are testing it against) |
| `doc_type` | circular / report / photo / attendance_sheet / certificate / other |
| `activity_title` | Title of the event/activity as written (short) |
| `activity_date` | YYYY-MM-DD if visible, else blank |
| `in_period` | yes / no / unknown — period is **1 Jul 2023 to 30 Jun 2024** |
| `seal_or_signature` | yes / no (is one VISIBLE? we never judge if it's genuine) |
| `fits_metric` | yes / no / unsure — use the metric rules below |
| `label` | **supports / weak / needs_review** (see decision rule) |
| `pii` | yes / no |
| `note` | anything odd (blurry, multiple events on one page, Telugu text, etc.) |

### Decision rule for `label`
- **supports** = fits the metric AND date is inside the period AND it clearly shows the activity.
- **weak** = clearly does NOT fit (wrong activity type, wrong year, duplicate, unrelated document).
- **needs_review** = can't tell (no date, unreadable, ambiguous, partly fits).

---

## Metric rules

**3.3.3 / 3.6.3 — Extension & outreach programmes**
- ✅ Activities FOR the community/society: NSS/NCC camps, blood donation, health camps, village/school visits,
  awareness drives (Swachh Bharat, voter, road safety), tree plantation, digital literacy for villagers.
- ❌ NOT outreach: internal fests, technical workshops only for own students, club meetings, hackathons, guest lectures.

**3.6.4 — Students participating in extension activities**
- ✅ Same activities as above, with a participant list/count. ❌ Lists from internal events.

**5.1.3 — Capacity building / skill enhancement for students**
- ✅ Soft skills, language/communication, life skills (yoga, health), ICT/computing skills programmes for students.
- ❌ Regular classes, faculty-only programmes.

**6.3.4 — Faculty Development Programmes (FDP) attended by teachers**
- ✅ FDP/refresher/orientation/short-term courses attended by teaching staff (certificate or list).
- ❌ Student events, non-teaching staff only.

**2.2.2 — Student : full-time teacher ratio**
- ✅ Official list of full-time teachers or enrolment statement for the year.
- ❌ Lists without year, part-time/guest faculty lists.

---

## Example
| item_id | metric | doc_type | activity_title | activity_date | in_period | seal_or_signature | fits_metric | label | pii | note |
|---|---|---|---|---|---|---|---|---|---|---|
| 3.6.3_1_p4-5 | 3.6.3 | report | Blood donation camp | 2023-09-14 | yes | yes | yes | supports | no | |
| 3.6.3_1_p9 | 3.6.3 | circular | 24-hr hackathon (CSE only) | 2024-02-05 | yes | yes | no | weak | no | internal event |

When done, send me your CSV. Don't look at the other person's file before finishing yours.
