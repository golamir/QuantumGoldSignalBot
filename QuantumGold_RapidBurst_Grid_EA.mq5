//+------------------------------------------------------------------+
//| QuantumGold_RapidBurst_Grid_EA.mq5                               |
//| XAU/USD fast scalping - two-sided pending burst engine           |
//| No martingale. Dynamic ATR spacing. M1 trigger + M5 context.      |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "QuantumGold RapidBurst - XAU/USD two-sided pending-order scalper"

#include <Trade/Trade.mqh>
CTrade trade;

//------------------------- Inputs -----------------------------------
input string InpSymbol              = "";      // Empty = chart symbol
input double InpLots                = 0.01;    // Base lot
input int    InpMagic                = 261005;  // EA magic number

input ENUM_TIMEFRAMES InpTriggerTF   = PERIOD_M1;
input ENUM_TIMEFRAMES InpContextTF   = PERIOD_M5;

input int    InpATRPeriod            = 14;
input double InpGridATRMult          = 0.55;    // Pending distance = ATR * multiplier
input double InpMinGridDistance     = 0.80;    // Price units, broker-dependent
input double InpMaxGridDistance     = 4.00;

input int    InpMaxPositions         = 5;
input int    InpMaxPendingOrders     = 2;
input int    InpPendingLifetimeSec   = 45;

input double InpTP_ATR               = 0.85;
input double InpSL_ATR               = 1.10;
input double InpEarlyTP_ATR          = 0.55;

input int    InpPullbackWindowSec    = 45;
input double InpPullbackATRMax       = 0.65;
input double InpReversalATR          = 0.85;

input int    InpCooldownSec          = 60;
input double InpMaxBasketLossMoney   = 5.00;
input double InpBasketProfitMoney    = 1.50;

// Progressive scale-in: add positions only after favorable movement.
input bool   InpProgressiveScaleIn     = true;
input double InpScaleInStepATR          = 0.55;
input int    InpMaxScaleIns             = 4;
input int    InpScaleInCooldownSec      = 8;
input bool   InpScaleInOnlyWhenProfit   = true;

input double InpMaxSpread            = 0.80;    // Price units; set for broker symbol
input int    InpADXPeriod            = 14;
input double InpMinADX               = 12.0;

input bool   InpUseM5Filter          = true;
input bool   InpUseBreakEven         = true;
input double InpBreakEvenATR         = 0.45;
input double InpBreakEvenOffset      = 0.05;

input bool   InpCancelOppositeOnEntry = true;
input bool   InpOneCycleAtATime       = true;

// Ultra-fast tick execution: direct market entry on a confirmed micro-burst.
input bool   InpFastExecution          = true;
input int    InpFastWindowMs           = 800;     // Detection window
input double InpFastMoveATR            = 0.12;    // Minimum burst = ATR * value
input double InpFastMinMove             = 0.08;    // Absolute minimum price move
input int    InpFastCooldownSec         = 3;       // Prevent repeated instant entries
input bool   InpFastRequireTwoTicks     = true;    // Require directional confirmation

//------------------------- State -----------------------------------
string g_symbol;
int    g_atrHandle = INVALID_HANDLE;
int    g_adxHandle = INVALID_HANDLE;
datetime g_lastCycle = 0;
ulong  g_cycleId = 0;
datetime g_lastScaleIn = 0;
ulong g_lastFastEntryMsc = 0;
double g_prevMid = 0.0;
ulong g_prevTickMsc = 0;
double g_fastStartMid = 0.0;
ulong g_fastStartMsc = 0;
int g_fastDirection = 0;

struct PositionState
{
   ulong ticket;
   ENUM_POSITION_TYPE type;
   double entry;
   double initialATR;
   datetime openTime;
   bool breakEvenDone;
};

PositionState g_pos[10];
int g_posCount = 0;

//------------------------- Utilities -------------------------------
double PointValue()
{
   return SymbolInfoDouble(g_symbol, SYMBOL_POINT);
}

int DigitsValue()
{
   return (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);
}

double NormalizePrice(double p)
{
   return NormalizeDouble(p, DigitsValue());
}

double NormalizeLots(double lots)
{
   double minLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_STEP);

   lots = MathMax(minLot, MathMin(maxLot, lots));
   if(step > 0)
      lots = MathFloor(lots / step) * step;

   return NormalizeDouble(lots, 2);
}

double GetATR()
{
   if(g_atrHandle == INVALID_HANDLE) return 0.0;
   double buf[3];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(g_atrHandle, 0, 0, 3, buf) < 2)
      return 0.0;
   return buf[0];
}

double GetADX()
{
   if(g_adxHandle == INVALID_HANDLE) return 0.0;
   double buf[3];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(g_adxHandle, 0, 0, 3, buf) < 2)
      return 0.0;
   return buf[0];
}

bool GetRates(ENUM_TIMEFRAMES tf, int count, MqlRates &rates[])
{
   ArraySetAsSeries(rates, true);
   int got = CopyRates(g_symbol, tf, 0, count, rates);
   return (got >= count);
}

double SpreadPrice()
{
   MqlTick t;
   if(!SymbolInfoTick(g_symbol, t)) return 999.0;
   return t.ask - t.bid;
}

bool IsGoldSymbol()
{
   string s = g_symbol;
   StringToUpper(s);
   return (StringFind(s, "XAU") >= 0 || StringFind(s, "GOLD") >= 0);
}

int CountOurPositions()
{
   int n = 0;
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;

      string sym = PositionGetString(POSITION_SYMBOL);
      long magic = PositionGetInteger(POSITION_MAGIC);

      if(sym == g_symbol && magic == InpMagic)
         n++;
   }
   return n;
}

int CountOurPending()
{
   int n = 0;
   for(int i=OrdersTotal()-1; i>=0; --i)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(!OrderSelect(ticket)) continue;

      string sym = OrderGetString(ORDER_SYMBOL);
      long magic = OrderGetInteger(ORDER_MAGIC);
      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);

      if(sym != g_symbol || magic != InpMagic) continue;

      if(type == ORDER_TYPE_BUY_STOP || type == ORDER_TYPE_SELL_STOP)
         n++;
   }
   return n;
}

double BasketProfit()
{
   double total = 0.0;

   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;

      if(PositionGetString(POSITION_SYMBOL) != g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      total += PositionGetDouble(POSITION_PROFIT);
      total += PositionGetDouble(POSITION_SWAP);
      total += PositionGetDouble(POSITION_COMMISSION);
   }
   return total;
}

void DeleteOurPending()
{
   for(int i=OrdersTotal()-1; i>=0; --i)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(!OrderSelect(ticket)) continue;

      if(OrderGetString(ORDER_SYMBOL) != g_symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;

      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type != ORDER_TYPE_BUY_STOP && type != ORDER_TYPE_SELL_STOP)
         continue;

      trade.OrderDelete(ticket);
   }
}

void CloseOurPositions()
{
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;

      if(PositionGetString(POSITION_SYMBOL) != g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      trade.PositionClose(ticket);
   }
}

bool CooldownPassed()
{
   return (TimeCurrent() - g_lastCycle >= InpCooldownSec);
}

//--------------------- Ultra-fast execution ------------------------
// Detect a short-lived directional burst directly from incoming ticks.
// This path intentionally bypasses slow confirmation filters such as ADX.
bool FastBurstEntry()
{
   if(!InpFastExecution) return false;
   if(CountOurPositions() > 0) return false;
   if(CountOurPending() > 0) return false;
   if(TimeCurrent() - g_lastCycle < InpFastCooldownSec) return false;

   MqlTick tick;
   if(!SymbolInfoTick(g_symbol, tick)) return false;
   if(tick.time_msc <= 0) return false;

   double spread = tick.ask - tick.bid;
   if(spread <= 0 || spread > InpMaxSpread) return false;

   double mid = (tick.ask + tick.bid) * 0.5;
   ulong now = (ulong)tick.time_msc;

   // Reset the micro-window when it expires.
   if(g_fastStartMsc == 0 || now < g_fastStartMsc || now - g_fastStartMsc > (ulong)InpFastWindowMs)
   {
      g_fastStartMsc = now;
      g_fastStartMid = mid;
      g_fastDirection = 0;
   }

   double tickDelta = mid - g_prevMid;
   if(g_prevTickMsc > 0 && tickDelta != 0.0)
   {
      int dir = (tickDelta > 0.0 ? 1 : -1);
      if(g_fastDirection == 0)
         g_fastDirection = dir;
      else if(dir != g_fastDirection)
      {
         // Direction changed: restart the burst measurement.
         g_fastStartMsc = now;
         g_fastStartMid = mid;
         g_fastDirection = dir;
      }
   }

   g_prevMid = mid;
   g_prevTickMsc = now;

   double atr = GetATR();
   if(atr <= 0) return false;

   double move = MathAbs(mid - g_fastStartMid);
   double threshold = MathMax(InpFastMinMove, atr * InpFastMoveATR);

   if(move < threshold) return false;
   if(g_fastDirection == 0) return false;
   if(InpFastRequireTwoTicks && g_prevTickMsc == 0) return false;

   // Avoid entering if the burst has already become too old.
   if(now - g_fastStartMsc > (ulong)InpFastWindowMs) return false;

   double lots = AdaptiveLot();
   if(lots <= 0) return false;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(30); // tighter execution tolerance for fast entries

   bool ok = false;
   if(g_fastDirection > 0)
   {
      double sl = NormalizePrice(tick.ask - atr * InpSL_ATR);
      double tp = NormalizePrice(tick.ask + atr * InpTP_ATR);
      ok = trade.Buy(lots, g_symbol, 0.0, sl, tp, "QG_FAST_BUY");
      if(ok)
         Print("QG FAST BUY | burst=", DoubleToString(move, DigitsValue()),
               " threshold=", DoubleToString(threshold, DigitsValue()),
               " ms=", (string)(now - g_fastStartMsc));
   }
   else
   {
      double sl = NormalizePrice(tick.bid + atr * InpSL_ATR);
      double tp = NormalizePrice(tick.bid - atr * InpTP_ATR);
      ok = trade.Sell(lots, g_symbol, 0.0, sl, tp, "QG_FAST_SELL");
      if(ok)
         Print("QG FAST SELL | burst=", DoubleToString(move, DigitsValue()),
               " threshold=", DoubleToString(threshold, DigitsValue()),
               " ms=", (string)(now - g_fastStartMsc));
   }

   if(ok)
   {
      g_lastFastEntryMsc = now;
      g_lastCycle = TimeCurrent();
      g_cycleId++;
      g_fastStartMsc = now;
      g_fastStartMid = mid;
      return true;
   }

   return false;
}

//---------------------- Context / Structure ------------------------
int M5Bias()
{
   MqlRates r[];
   if(!GetRates(InpContextTF, 4, r))
      return 0;

   double c1 = r[1].close;
   double c2 = r[2].close;
   double h2 = r[2].high;
   double l2 = r[2].low;

   if(c1 > c2 && c1 > h2)
      return 1;
   if(c1 < c2 && c1 < l2)
      return -1;

   // Soft trend using last two closed candles
   if(c1 > c2) return 1;
   if(c1 < c2) return -1;

   return 0;
}

bool MarketFilterOK()
{
   if(!IsGoldSymbol())
   {
      Print("QuantumGold: chart symbol does not look like XAU/GOLD. EA will not trade.");
      return false;
   }

   double spread = SpreadPrice();
   if(spread <= 0 || spread > InpMaxSpread)
      return false;

   double adx = GetADX();
   if(adx < InpMinADX)
      return false;

   return true;
}

//------------------------- Pending cycle ----------------------------
void PlaceCycle()
{
   if(!CooldownPassed()) return;
   if(CountOurPositions() > 0 && InpOneCycleAtATime) return;
   if(CountOurPending() >= InpMaxPendingOrders) return;
   if(!MarketFilterOK()) return;

   double atr = GetATR();
   if(atr <= 0) return;

   double step = atr * InpGridATRMult;
   step = MathMax(step, InpMinGridDistance);
   step = MathMin(step, InpMaxGridDistance);

   MqlTick tick;
   if(!SymbolInfoTick(g_symbol, tick)) return;

   // Broker stop level protection
   double minStop = (double)SymbolInfoInteger(g_symbol, SYMBOL_TRADE_STOPS_LEVEL) * PointValue();
   step = MathMax(step, minStop + 2.0 * PointValue());

   int bias = M5Bias();

   // Two-sided pending orders remain the core engine.
   // M5 is a SOFT filter: it can suppress the weaker side only when very clear.
   bool allowBuy  = true;
   bool allowSell = true;

   if(InpUseM5Filter)
   {
      if(bias >= 2) allowSell = false;
      if(bias <= -2) allowBuy = false;
   }

   double buyPrice  = NormalizePrice(tick.ask + step);
   double sellPrice = NormalizePrice(tick.bid - step);

   double slBuy  = NormalizePrice(buyPrice  - atr * InpSL_ATR);
   double tpBuy  = NormalizePrice(buyPrice  + atr * InpTP_ATR);
   double slSell = NormalizePrice(sellPrice + atr * InpSL_ATR);
   double tpSell = NormalizePrice(sellPrice - atr * InpTP_ATR);

   double lots = AdaptiveLot();
   if(lots <= 0) return;

   datetime expiry = TimeCurrent() + InpPendingLifetimeSec;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);

   bool ok1 = false, ok2 = false;

   if(allowBuy)
   {
      ok1 = trade.BuyStop(
         lots, buyPrice, g_symbol,
         slBuy, tpBuy,
         ORDER_TIME_SPECIFIED, expiry,
         "QG_RB_BUY"
      );
      if(!ok1)
         Print("QG BUY STOP failed: ", trade.ResultRetcodeDescription());
   }

   if(allowSell)
   {
      ok2 = trade.SellStop(
         lots, sellPrice, g_symbol,
         slSell, tpSell,
         ORDER_TIME_SPECIFIED, expiry,
         "QG_RB_SELL"
      );
      if(!ok2)
         Print("QG SELL STOP failed: ", trade.ResultRetcodeDescription());
   }

   if(ok1 || ok2)
   {
      g_lastCycle = TimeCurrent();
      g_cycleId++;
      Print("QG RapidBurst cycle #", g_cycleId,
            " ATR=", DoubleToString(atr, DigitsValue()),
            " step=", DoubleToString(step, DigitsValue()),
            " M5Bias=", bias);
   }
}

double AdaptiveLot()
{
   double lot=InpLotAtStart;
   double realized=0.0;
   if(InpProfitLotScaling && InpProfitStepUSD>0.0 && HistorySelect(0,TimeCurrent()))
   {
      int n=HistoryDealsTotal();
      for(int i=0;i<n;i++)
      {
         ulong d=HistoryDealGetTicket(i);
         if(d==0) continue;
         if(HistoryDealGetString(d,DEAL_SYMBOL)!=g_symbol) continue;
         if((long)HistoryDealGetInteger(d,DEAL_MAGIC)!=InpMagic) continue;
         long e=HistoryDealGetInteger(d,DEAL_ENTRY);
         if(e==DEAL_ENTRY_OUT || e==DEAL_ENTRY_OUT_BY)
            realized += HistoryDealGetDouble(d,DEAL_PROFIT)+HistoryDealGetDouble(d,DEAL_SWAP)+HistoryDealGetDouble(d,DEAL_COMMISSION);
      }
      if(realized>0.0) lot += MathFloor(realized/InpProfitStepUSD)*InpLotPerProfitStep;
   }
   lot=MathMin(lot,InpMaxAdaptiveLot);
   return NormalizeLots(lot);
}

//--------------------- Progressive scale-in -----------------------
// Adds positions only in the direction that is already moving correctly.
// This is NOT martingale: lot size stays fixed and no add is allowed
// because of a losing position.
void ProgressiveScaleIn()
{
   if(!InpProgressiveScaleIn) return;
   if(CountOurPositions() <= 0) return;
   if(CountOurPositions() >= InpMaxPositions) return;
   if(TimeCurrent() - g_lastScaleIn < InpScaleInCooldownSec) return;

   double atr = GetATR();
   if(atr <= 0) return;

   MqlTick tick;
   if(!SymbolInfoTick(g_symbol, tick)) return;

   double lots = AdaptiveLot();
   if(lots <= 0) return;

   int buyCount = 0;
   int sellCount = 0;
   double lastBuyEntry = 0.0;
   double lastSellEntry = 0.0;
   double totalProfit = 0.0;

   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      ENUM_POSITION_TYPE type =
         (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double profit = PositionGetDouble(POSITION_PROFIT);

      totalProfit += profit;

      if(type == POSITION_TYPE_BUY)
      {
         buyCount++;
         if(lastBuyEntry == 0.0 || entry > lastBuyEntry)
            lastBuyEntry = entry;
      }
      else if(type == POSITION_TYPE_SELL)
      {
         sellCount++;
         if(lastSellEntry == 0.0 || entry < lastSellEntry)
            lastSellEntry = entry;
      }
   }

   if(InpScaleInOnlyWhenProfit && totalProfit <= 0.0)
      return;

   // Scale only the dominant direction. If both directions exist,
   // do not add until one side clearly has the basket advantage.
   if(buyCount > 0 && sellCount == 0)
   {
      double advance = tick.bid - lastBuyEntry;

      if(advance >= atr * InpScaleInStepATR)
      {
         double sl = NormalizePrice(tick.ask - atr * InpSL_ATR);
         double tp = NormalizePrice(tick.ask + atr * InpTP_ATR);

         trade.SetExpertMagicNumber(InpMagic);
         if(trade.Buy(lots, g_symbol, 0.0, sl, tp, "QG_SCALE_BUY"))
         {
            g_lastScaleIn = TimeCurrent();
            Print("QG SCALE-IN BUY #", buyCount + 1,
                  " advance=", DoubleToString(advance, DigitsValue()));
         }
      }
   }
   else if(sellCount > 0 && buyCount == 0)
   {
      double advance = lastSellEntry - tick.ask;

      if(advance >= atr * InpScaleInStepATR)
      {
         double sl = NormalizePrice(tick.bid + atr * InpSL_ATR);
         double tp = NormalizePrice(tick.bid - atr * InpTP_ATR);

         trade.SetExpertMagicNumber(InpMagic);
         if(trade.Sell(lots, g_symbol, 0.0, sl, tp, "QG_SCALE_SELL"))
         {
            g_lastScaleIn = TimeCurrent();
            Print("QG SCALE-IN SELL #", sellCount + 1,
                  " advance=", DoubleToString(advance, DigitsValue()));
         }
      }
   }
}

//--------------------- Active trade management ---------------------
bool GetOurPositionData(ulong ticket,
                         ENUM_POSITION_TYPE &ptype,
                         double &entry,
                         double &sl,
                         double &tp,
                         datetime &openTime)
{
   if(!PositionSelectByTicket(ticket)) return false;

   if(PositionGetString(POSITION_SYMBOL) != g_symbol) return false;
   if(PositionGetInteger(POSITION_MAGIC) != InpMagic) return false;

   ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   entry = PositionGetDouble(POSITION_PRICE_OPEN);
   sl    = PositionGetDouble(POSITION_SL);
   tp    = PositionGetDouble(POSITION_TP);
   openTime = (datetime)PositionGetInteger(POSITION_TIME);

   return true;
}

void ManagePositions()
{
   int count = CountOurPositions();
   if(count <= 0) return;

   double atr = GetATR();
   if(atr <= 0) return;

   double basket = BasketProfit();

   if(basket >= InpBasketProfitMoney)
   {
      Print("QG Basket TP reached: ", DoubleToString(basket,2));
      DeleteOurPending();
      CloseOurPositions();
      g_lastCycle = TimeCurrent();
      return;
   }

   if(basket <= -MathAbs(InpMaxBasketLossMoney))
   {
      Print("QG Basket LOSS limit reached: ", DoubleToString(basket,2));
      DeleteOurPending();
      CloseOurPositions();
      g_lastCycle = TimeCurrent();
      return;
   }

   MqlTick tick;
   if(!SymbolInfoTick(g_symbol, tick)) return;

   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;

      ENUM_POSITION_TYPE type;
      double entry, sl, tp;
      datetime openTime;

      if(!GetOurPositionData(ticket, type, entry, sl, tp, openTime))
         continue;

      double profitDistance = 0.0;
      double adverseDistance = 0.0;

      if(type == POSITION_TYPE_BUY)
      {
         profitDistance = tick.bid - entry;
         adverseDistance = entry - tick.bid;
      }
      else
      {
         profitDistance = entry - tick.ask;
         adverseDistance = tick.ask - entry;
      }

      // Break-even after a meaningful first burst.
      if(InpUseBreakEven && profitDistance >= atr * InpBreakEvenATR)
      {
         double newSL;

         if(type == POSITION_TYPE_BUY)
            newSL = NormalizePrice(entry + InpBreakEvenOffset);
         else
            newSL = NormalizePrice(entry - InpBreakEvenOffset);

         bool improve = false;

         if(type == POSITION_TYPE_BUY)
            improve = (sl == 0.0 || newSL > sl);
         else
            improve = (sl == 0.0 || newSL < sl);

         if(improve)
         {
            trade.PositionModify(ticket, newSL, tp);
         }
      }

      // Detect a strong adverse burst. This is the "real reversal" guard.
      if(adverseDistance >= atr * InpReversalATR)
      {
         Print("QG strong adverse burst -> closing ticket ", ticket);
         trade.PositionClose(ticket);
      }
   }

   // Once a position is active, cancel the opposite pending order.
   if(InpCancelOppositeOnEntry)
   {
      DeleteOurPending();
   }
}

//--------------------- Pullback logic -------------------------------
void ManagePullbackBehavior()
{
   if(CountOurPositions() <= 0) return;

   double atr = GetATR();
   if(atr <= 0) return;

   MqlRates r[];
   if(!GetRates(InpTriggerTF, 4, r)) return;

   MqlTick tick;
   if(!SymbolInfoTick(g_symbol, tick)) return;

   // The closed M1 candle is used to distinguish a small pullback
   // from a decisive reversal. Small pullbacks are intentionally ignored.
   double body = MathAbs(r[1].close - r[1].open);
   double range = r[1].high - r[1].low;

   if(range <= 0) return;

   bool strongOppositeCandle = (body / range >= 0.70);

   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;

      ENUM_POSITION_TYPE type;
      double entry, sl, tp;
      datetime openTime;

      if(!GetOurPositionData(ticket, type, entry, sl, tp, openTime))
         continue;

      // Only act within the short post-entry window.
      if(TimeCurrent() - openTime > InpPullbackWindowSec)
         continue;

      double adverse = 0.0;

      if(type == POSITION_TYPE_BUY)
         adverse = entry - tick.bid;
      else
         adverse = tick.ask - entry;

      // Small pullback: keep the trade alive.
      if(adverse >= 0 && adverse <= atr * InpPullbackATRMax)
         continue;

      // Large adverse movement + strong opposite candle = exit.
      if(adverse > atr * InpPullbackATRMax && strongOppositeCandle)
      {
         Print("QG Pullback->Reversal detected, closing ", ticket);
         trade.PositionClose(ticket);
      }
   }
}


void CloseOurPositionsByType(ENUM_POSITION_TYPE wanted)
{
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=wanted) continue;
      trade.PositionClose(ticket);
   }
}

void CheckRapidReversal()
{
   if(!InpFastExecution) return;
   MqlTick tick;
   if(!SymbolInfoTick(g_symbol,tick)) return;
   double atr=GetATR();
   if(atr<=0) return;

   static double prevMid=0.0;
   static double momentum=0.0;
   double mid=(tick.bid+tick.ask)*0.5;
   if(prevMid>0) momentum += mid-prevMid;
   prevMid=mid;

   int buys=0,sells=0;
   for(int i=PositionsTotal()-1;i>=0;--i)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      ENUM_POSITION_TYPE t=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if(t==POSITION_TYPE_BUY) buys++;
      else if(t==POSITION_TYPE_SELL) sells++;
   }

   double threshold=atr*0.18;
   if(buys>0 && momentum < -threshold)
   {
      CloseOurPositionsByType(POSITION_TYPE_BUY);
      trade.SetExpertMagicNumber(InpMagic);
      trade.SetDeviationInPoints(50);
      double sl=tick.bid+atr*InpSL_ATR;
      double tp=tick.bid-atr*InpTP_ATR;
      trade.Sell(AdaptiveLot(),g_symbol,0.0,NormalizePrice(sl),NormalizePrice(tp),"QG REVERSAL SELL");
      momentum=0.0;
      g_lastCycle=TimeCurrent();
   }
   else if(sells>0 && momentum > threshold)
   {
      CloseOurPositionsByType(POSITION_TYPE_SELL);
      trade.SetExpertMagicNumber(InpMagic);
      trade.SetDeviationInPoints(50);
      double sl=tick.ask-atr*InpSL_ATR;
      double tp=tick.ask+atr*InpTP_ATR;
      trade.Buy(AdaptiveLot(),g_symbol,0.0,NormalizePrice(sl),NormalizePrice(tp),"QG REVERSAL BUY");
      momentum=0.0;
      g_lastCycle=TimeCurrent();
   }
   else if(MathAbs(momentum) > atr*0.50)
      momentum=0.0;
}

//------------------------- Lifecycle -------------------------------
int OnInit()
{
   g_symbol = InpSymbol;
   if(g_symbol == "")
      g_symbol = _Symbol;

   if(!SymbolSelect(g_symbol, true))
   {
      Print("Cannot select symbol: ", g_symbol);
      return INIT_FAILED;
   }

   if(!IsGoldSymbol())
   {
      Print("Attach this EA to an XAU/USD or GOLD symbol. Current: ", g_symbol);
      return INIT_FAILED;
   }

   g_atrHandle = iATR(g_symbol, InpTriggerTF, InpATRPeriod);
   if(g_atrHandle == INVALID_HANDLE)
   {
      Print("ATR handle failed.");
      return INIT_FAILED;
   }

   g_adxHandle = iADX(g_symbol, InpTriggerTF, InpADXPeriod);
   if(g_adxHandle == INVALID_HANDLE)
   {
      Print("ADX handle failed.");
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);

   Print("================================================");
   Print("QuantumGold RapidBurst Grid EA 1.00");
   Print("XAU/USD | M1 trigger + M5 context");
   Print("Two-sided pending orders | NO martingale");
   Print("Automatic SL/TP + BE + basket protection");
   Print("Symbol: ", g_symbol);
   Print("================================================");

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(g_atrHandle != INVALID_HANDLE)
      IndicatorRelease(g_atrHandle);

   if(g_adxHandle != INVALID_HANDLE)
      IndicatorRelease(g_adxHandle);
}

void OnTick()
{
   // Highest priority: protect/manage existing exposure.
   ManagePositions();
   ManagePullbackBehavior();
   CheckRapidReversal();
   ProgressiveScaleIn();

   // Fast path: act directly on a confirmed micro-burst from live ticks.
   // This intentionally runs before ADX/M5/candle-based cycle creation.
   if(FastBurstEntry())
      return;

   // Do not create a new cycle while positions exist.
   if(InpOneCycleAtATime && CountOurPositions() > 0)
      return;

   // If no direct burst was detected, keep the two-sided pending grid ready.
   if(CountOurPending() == 0)
      PlaceCycle();
}
