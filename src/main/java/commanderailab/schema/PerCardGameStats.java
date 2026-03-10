package commanderailab.schema;

/**
 * Per-card statistics for a single game.
 * Tracks what happened to each card during one simulation game.
 * Attached to PlayerResult as a list.
 */
public class PerCardGameStats {

    public String cardName;

    // ── Draw/Cast tracking ────────────────────────────────────
    public boolean drawn;
    public int turnDrawn = -1;         // -1 if not drawn
    public boolean inOpeningHand;
    public boolean keptInOpeningHand;   // false if mulliganed away

    public boolean cast;
    public int turnCast = -1;          // -1 if not cast

    // ── Board/hand state ──────────────────────────────────────
    public boolean stuckInHand;         // drawn but never cast/used
    public boolean onBattlefieldAtEnd;  // was on battlefield when game ended

    // ── Combat/value tracking ─────────────────────────────────
    public int damageDealt;
    public int manaProduced;
    public int tokensCreated;

    // ── Constructors ──────────────────────────────────────────

    public PerCardGameStats() {}

    public PerCardGameStats(String cardName) {
        this.cardName = cardName;
    }

    /**
     * Mark card as a "dead card" — drawn but never cast and still in hand
     * at end of game.
     */
    public void computeStuckInHand() {
        this.stuckInHand = drawn && !cast;
    }

    @Override
    public String toString() {
        return String.format("PerCardGameStats{%s drawn=%b cast=%b stuck=%b dmg=%d}",
                cardName, drawn, cast, stuckInHand, damageDealt);
    }
}
