-- One grant per payment, enforced by the store (FR-009).
--
-- `UNIQUE (method, provider_ref)` on `payments` stops the same Steam offer being recorded
-- as two payments. It does NOT stop one payment being granted twice, and under a
-- concurrent engine that gap is reachable: `reconcile_offer` claims the offer and commits,
-- then completes it in a second transaction. A poller arriving between those two commits
-- finds the payment already claimed, skips the claim gate on that basis, and grants again.
-- Twelve concurrent replays of one payment produced three grants before this index existed.
--
-- FR-009 is explicit that exactly-once "MUST be guaranteed by the store itself, not only
-- by the code paths that call it". `payments._complete` now also does a compare-and-set on
-- the payment's state, which is what makes the normal path correct; this index is what
-- makes it *true* — no future caller, poller, or hand-run backfill can grant a payment
-- twice, whatever it believes about the state it read.
--
-- Partial, because `payment_id` is NULL for every reserve, release and extend entry, and
-- those must stay unconstrained. `kind = 'grant'` because a payment legitimately relates
-- to other ledger movements.
CREATE UNIQUE INDEX idx_credit_ledger_one_grant_per_payment
    ON credit_ledger (payment_id)
    WHERE kind = 'grant' AND payment_id IS NOT NULL;
