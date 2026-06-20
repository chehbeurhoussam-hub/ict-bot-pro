import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ict_engine import _ema, get_ote_zone, calculate_confluence, check_mss
from risk_manager import check_rr_with_fees, calculate_position_size
from state_logger import StateManager, BotState

# ==========================================
# Unit Tests for ICT Engine
# ==========================================
class TestICTEngine(unittest.TestCase):

    def test_ema_calculation(self):
        """Test EMA starts from most recent data"""
        closes = [100, 102, 101, 103, 105, 104, 106]
        ema = _ema(closes, 5)
        # EMA should be weighted toward recent values (106, 104, 105...)
        self.assertGreater(ema, 100)  # Should be influenced by recent high values
        self.assertLess(ema, 110)

    def test_ote_zone_bullish(self):
        """Test OTE zone for bullish direction"""
        # Create fake candles: [timestamp, open, high, low, close, volume]
        candles = [
            [0, 100, 110, 95, 105, 1000],
            [0, 105, 115, 100, 110, 1000],
            [0, 110, 120, 105, 115, 1000],
        ]
        ote = get_ote_zone(candles, 'BULLISH')
        self.assertLess(ote['low'], ote['high'])
        self.assertLess(ote['sl_ref'], ote['low'])  # SL below OTE

    def test_ote_zone_bearish(self):
        """Test OTE zone for bearish direction"""
        candles = [
            [0, 120, 125, 110, 115, 1000],
            [0, 115, 120, 105, 110, 1000],
            [0, 110, 115, 100, 105, 1000],
        ]
        ote = get_ote_zone(candles, 'BEARISH')
        self.assertLess(ote['low'], ote['high'])
        self.assertGreater(ote['sl_ref'], ote['high'])  # SL above OTE

    def test_confluence_scoring(self):
        """Test confluence scoring"""
        ob = {'high': 100, 'low': 90}
        fvg = {'high': 105, 'low': 95}
        rb = {'high': 102, 'low': 92}

        conf = calculate_confluence(ob, fvg, rb, True)
        self.assertEqual(conf['score'], 4)

        conf = calculate_confluence(None, None, None, False)
        self.assertEqual(conf['score'], 0)

    def test_mss_bullish(self):
        """Test MSS bullish detection"""
        candles = [
            [0, 100, 105, 98, 102],   # c1
            [0, 102, 108, 101, 107],  # c2 - breaks above c1 high
            [0, 107, 112, 106, 110],  # c3 - confirms above c2 high
        ]
        self.assertTrue(check_mss(candles, 'BULLISH'))

    def test_mss_bearish(self):
        """Test MSS bearish detection"""
        candles = [
            [0, 110, 112, 105, 108],  # c1
            [0, 108, 109, 102, 104],  # c2 - breaks below c1 low
            [0, 104, 105, 100, 101],  # c3 - confirms below c2 low
        ]
        self.assertTrue(check_mss(candles, 'BEARISH'))

    def test_mss_not_confirmed(self):
        """Test MSS not confirmed"""
        candles = [
            [0, 100, 105, 98, 102],
            [0, 102, 103, 101, 102],  # No break
            [0, 102, 104, 101, 103],  # No confirmation
        ]
        self.assertFalse(check_mss(candles, 'BULLISH'))

# ==========================================
# Unit Tests for Risk Manager
# ==========================================
class TestRiskManager(unittest.TestCase):

    def test_rr_with_fees(self):
        """Test RR calculation with fees"""
        entry = 50000
        sl = 49000
        tp = 52000

        ok, rr = check_rr_with_fees(entry, sl, tp)
        self.assertTrue(ok)
        self.assertGreater(rr, 1.5)

    def test_rr_below_minimum(self):
        """Test RR below minimum"""
        entry = 50000
        sl = 49000
        tp = 50500  # Very close to entry

        ok, rr = check_rr_with_fees(entry, sl, tp, min_rr=2.0)
        self.assertFalse(ok)

    def test_position_size(self):
        """Test position size calculation"""
        balance = 10000
        entry = 50000
        sl = 49000

        size = calculate_position_size(balance, entry, sl)
        self.assertGreater(size, 0)
        # Risk = 1% of 10000 = 100, risk per unit = 1000
        # size = 100 / 1000 * leverage (5x) = 0.5
        self.assertAlmostEqual(size, 0.5, places=1)

    def test_zero_risk(self):
        """Test position size with zero risk"""
        size = calculate_position_size(10000, 50000, 50000)
        self.assertEqual(size, 0.0)

# ==========================================
# Unit Tests for State Manager
# ==========================================
class TestStateManager(unittest.TestCase):

    def test_state_transition(self):
        """Test state transitions"""
        sm = StateManager()
        self.assertEqual(sm.state, BotState.WAITING_KILL_ZONE)

        sm.transition(BotState.SCANNING)
        self.assertEqual(sm.state, BotState.SCANNING)
        self.assertEqual(sm.prev_state, BotState.WAITING_KILL_ZONE)

    def test_trade_data(self):
        """Test trade data management"""
        sm = StateManager()
        trade = {'entry': 50000, 'signal': 'BUY'}
        sm.set_trade(trade)
        self.assertEqual(sm.state, BotState.IN_TRADE)
        self.assertEqual(sm.trade_data, trade)

    def test_emergency_stop(self):
        """Test emergency stop"""
        sm = StateManager()
        sm.transition(BotState.SCANNING)
        sm.emergency_stop()
        self.assertEqual(sm.state, BotState.EMERGENCY_STOP)

# ==========================================
# Run Tests
# ==========================================
if __name__ == '__main__':
    unittest.main(verbosity=2)
