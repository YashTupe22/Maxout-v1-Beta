//+------------------------------------------------------------------+
//|                                                RiskProtection.mqh|
//|               MaxOut AI Trading — Capital Protection & Guardrails|
//+------------------------------------------------------------------+
#ifndef __AI_RISK_PROTECTION_MQH__
#define __AI_RISK_PROTECTION_MQH__

#include <Trade\SymbolInfo.mqh>
#include <Trade\AccountInfo.mqh>

class CRiskProtection
  {
protected:
   CSymbolInfo       m_symbol;
   CAccountInfo      m_account;
   
   // Max spread protection
   bool              m_enable_max_spread;
   int               m_max_spread_points;
   
   // Daily loss circuit breaker
   bool              m_enable_daily_drawdown;
   double            m_max_daily_drawdown_pct;
   string            m_cb_file;
   
   // Internal state
   double            m_daily_start_equity;
   datetime          m_last_day_ts;
   bool              m_circuit_breaker_active;
   string            m_circuit_breaker_reason;
   
   void              LoadCircuitBreakerState(void);
   void              SaveCircuitBreakerState(void);
   bool              CheckNewDayReset(void);

public:
                     CRiskProtection(void);
                    ~CRiskProtection(void);
                    
   bool              Init(const string symbol);
   void              ConfigureSpread(const bool enable, const int max_spread_points)
                       { m_enable_max_spread = enable; m_max_spread_points = max_spread_points; }
   void              ConfigureDailyDrawdown(const bool enable, const double max_drawdown_pct)
                       { m_enable_daily_drawdown = enable; m_max_daily_drawdown_pct = max_drawdown_pct; }

   bool              ValidateNewOrder(string &reject_reason);
   bool              ValidateStops(const string symbol, const ENUM_ORDER_TYPE order_type, 
                                   const double price, const double sl, const double tp, 
                                   string &reject_reason);

   // Sizing helper matching CMoneyFixedRisk
   double            CalculateRiskLot(const string symbol, const ENUM_ORDER_TYPE order_type,
                                      const double price, const double sl, const double risk_percent);

   // Status accessors
   bool              IsCircuitBreakerActive(void)  const { return m_circuit_breaker_active; }
   double            DailyStartEquity(void)        const { return m_daily_start_equity; }
   double            CurrentEquity(void)           const { return m_account.Equity(); }
   double            DailyDrawdownPct(void)        const;
   int               CurrentSpreadPoints(void);
   int               MaxSpreadPoints(void)         const { return m_max_spread_points; }
   bool              IsMaxSpreadEnabled(void)      const { return m_enable_max_spread; }
   bool              IsDailyDrawdownEnabled(void)  const { return m_enable_daily_drawdown; }
   double            MaxDailyDrawdownPct(void)     const { return m_max_daily_drawdown_pct; }
   string            CircuitBreakerReason(void)    const { return m_circuit_breaker_reason; }
  };

//+------------------------------------------------------------------+
//| Constructor                                                      |
//+------------------------------------------------------------------+
CRiskProtection::CRiskProtection(void) : m_enable_max_spread(true),
                                         m_max_spread_points(30),
                                         m_enable_daily_drawdown(true),
                                         m_max_daily_drawdown_pct(3.0),
                                         m_cb_file("AI\\circuit_breaker.json"),
                                         m_daily_start_equity(0.0),
                                         m_last_day_ts(0),
                                         m_circuit_breaker_active(false),
                                         m_circuit_breaker_reason("")
  {
  }

//+------------------------------------------------------------------+
//| Destructor                                                       |
//+------------------------------------------------------------------+
CRiskProtection::~CRiskProtection(void)
  {
  }

//+------------------------------------------------------------------+
//| Initialization                                                   |
//+------------------------------------------------------------------+
bool CRiskProtection::Init(const string symbol)
  {
   if(!m_symbol.Name(symbol))
     {
      PrintFormat("CRiskProtection: cannot initialize symbol %s", symbol);
      return false;
     }
   LoadCircuitBreakerState();
   CheckNewDayReset();
   return true;
  }

//+------------------------------------------------------------------+
//| Check Day boundary reset                                         |
//+------------------------------------------------------------------+
bool CRiskProtection::CheckNewDayReset(void)
  {
   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);
   
   // Server day stamp (midnight 00:00:00 of current date)
   dt.hour = 0;
   dt.min = 0;
   dt.sec = 0;
   datetime today_midnight = StructToTime(dt);

   if(m_last_day_ts == 0 || today_midnight > m_last_day_ts)
     {
      // If a circuit breaker was triggered, keep it locked until the server day rollover
      if(m_last_day_ts > 0 && today_midnight > m_last_day_ts)
        {
         if(m_circuit_breaker_active)
           {
            PrintFormat("CRiskProtection: Server day rollover from %s to %s. Resetting circuit breaker lock.",
                        TimeToString(m_last_day_ts, TIME_DATE), TimeToString(today_midnight, TIME_DATE));
            m_circuit_breaker_active = false;
            m_circuit_breaker_reason = "";
           }
        }

      m_last_day_ts = today_midnight;
      m_daily_start_equity = m_account.Equity();
      SaveCircuitBreakerState();
      PrintFormat("CRiskProtection: Day baseline anchored at %s. Start equity: $%.2f",
                  TimeToString(today_midnight, TIME_DATE), m_daily_start_equity);
      return true;
     }

   return false;
  }

//+------------------------------------------------------------------+
//| Load Circuit Breaker state from common file                      |
//+------------------------------------------------------------------+
void CRiskProtection::LoadCircuitBreakerState(void)
  {
   if(!FileIsExist(m_cb_file, FILE_COMMON))
      return;

   int h = FileOpen(m_cb_file, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;

   string content = FileReadString(h);
   FileClose(h);

   // Simple JSON parsing
   int pos_locked = StringFind(content, "\"locked\":");
   if(pos_locked >= 0)
     {
      string val = StringSubstr(content, pos_locked + 9, 5);
      m_circuit_breaker_active = (StringFind(val, "true") >= 0);
     }
   int pos_eq = StringFind(content, "\"start_equity\":");
   if(pos_eq >= 0)
     {
      string val = StringSubstr(content, pos_eq + 15, 16);
      m_daily_start_equity = StringToDouble(val);
     }
   int pos_day = StringFind(content, "\"day_ts\":");
   if(pos_day >= 0)
     {
      string val = StringSubstr(content, pos_day + 9, 14);
      m_last_day_ts = (datetime)StringToInteger(val);
     }
   int pos_reason = StringFind(content, "\"reason\":");
   if(pos_reason >= 0)
     {
      int start = pos_reason + 10;
      int end = StringFind(content, "\"", start);
      if(end > start)
         m_circuit_breaker_reason = StringSubstr(content, start, end - start);
     }
  }

//+------------------------------------------------------------------+
//| Save Circuit Breaker state to common file                        |
//+------------------------------------------------------------------+
void CRiskProtection::SaveCircuitBreakerState(void)
  {
   int h = FileOpen(m_cb_file, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;

   string json = StringFormat(
      "{\"updated\":\"%s\",\"day_ts\":%I64d,\"start_equity\":%.2f,\"locked\":%s,\"drawdown_pct\":%.2f,\"reason\":\"%s\"}",
      TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS),
      (long)m_last_day_ts,
      m_daily_start_equity,
      m_circuit_breaker_active ? "true" : "false",
      DailyDrawdownPct(),
      m_circuit_breaker_reason
   );
   FileWriteString(h, json);
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| Daily Drawdown percentage calculation                            |
//+------------------------------------------------------------------+
double CRiskProtection::DailyDrawdownPct(void) const
  {
   if(m_daily_start_equity <= 0.0)
      return 0.0;
   double cur_eq = m_account.Equity();
   if(cur_eq >= m_daily_start_equity)
      return 0.0;
   return ((m_daily_start_equity - cur_eq) / m_daily_start_equity) * 100.0;
  }

//+------------------------------------------------------------------+
//| Get Current Spread in points                                     |
//+------------------------------------------------------------------+
int CRiskProtection::CurrentSpreadPoints(void)
  {
   m_symbol.RefreshRates();
   double ask = m_symbol.Ask();
   double bid = m_symbol.Bid();
   double pt = m_symbol.Point();
   if(pt <= 0.0)
      return 0;
   return (int)MathRound((ask - bid) / pt);
  }

//+------------------------------------------------------------------+
//| Validate whether an order is permitted under risk rules          |
//+------------------------------------------------------------------+
bool CRiskProtection::ValidateNewOrder(string &reject_reason)
  {
   CheckNewDayReset();

   // 1. Check Circuit Breaker
   if(m_circuit_breaker_active)
     {
      reject_reason = StringFormat("Circuit Breaker ACTIVE: %s", m_circuit_breaker_reason);
      PrintFormat("CRiskProtection: [BLOCKED] %s", reject_reason);
      return false;
     }

   // 2. Check Daily Drawdown Limit
   if(m_enable_daily_drawdown)
     {
      double dd = DailyDrawdownPct();
      if(dd >= m_max_daily_drawdown_pct)
        {
         m_circuit_breaker_active = true;
         m_circuit_breaker_reason = StringFormat("Daily drawdown reached %.2f%% (limit: %.2f%%)", 
                                                 dd, m_max_daily_drawdown_pct);
         SaveCircuitBreakerState();
         reject_reason = m_circuit_breaker_reason;
         PrintFormat("CRiskProtection: [CIRCUIT BREAKER TRIGGERED] %s. All new entries locked for remainder of day.", 
                     reject_reason);
         return false;
        }
     }

   // 3. Check Max Spread Filter
   if(m_enable_max_spread)
     {
      int current_spread = CurrentSpreadPoints();
      if(current_spread > m_max_spread_points)
        {
         reject_reason = StringFormat("Spread too wide: %d points (max allowed: %d points)",
                                      current_spread, m_max_spread_points);
         PrintFormat("CRiskProtection: [SPREAD REJECTION] %s", reject_reason);
         return false;
        }
     }

   return true;
  }

//+------------------------------------------------------------------+
//| Validate Stop Loss & Take Profit against broker specifications   |
//+------------------------------------------------------------------+
bool CRiskProtection::ValidateStops(const string symbol, const ENUM_ORDER_TYPE order_type,
                                   const double price, const double sl, const double tp,
                                   string &reject_reason)
  {
   m_symbol.RefreshRates();
   double pt = m_symbol.Point();
   int stops_level = (int)m_symbol.StopsLevel();
   double min_stop_dist = stops_level * pt;

   if(order_type == ORDER_TYPE_BUY)
     {
      if(sl > 0.0)
        {
         if(sl >= price)
           {
            reject_reason = StringFormat("Buy SL (%.5f) must be below entry price (%.5f)", sl, price);
            return false;
           }
         if((price - sl) < min_stop_dist)
           {
            reject_reason = StringFormat("Buy SL distance (%.5f) is less than broker stop level (%.5f / %d pts)",
                                         price - sl, min_stop_dist, stops_level);
            return false;
           }
        }
      if(tp > 0.0)
        {
         if(tp <= price)
           {
            reject_reason = StringFormat("Buy TP (%.5f) must be above entry price (%.5f)", tp, price);
            return false;
           }
         if((tp - price) < min_stop_dist)
           {
            reject_reason = StringFormat("Buy TP distance (%.5f) is less than broker stop level (%.5f / %d pts)",
                                         tp - price, min_stop_dist, stops_level);
            return false;
           }
        }
     }
   else if(order_type == ORDER_TYPE_SELL)
     {
      if(sl > 0.0)
        {
         if(sl <= price)
           {
            reject_reason = StringFormat("Sell SL (%.5f) must be above entry price (%.5f)", sl, price);
            return false;
           }
         if((sl - price) < min_stop_dist)
           {
            reject_reason = StringFormat("Sell SL distance (%.5f) is less than broker stop level (%.5f / %d pts)",
                                         sl - price, min_stop_dist, stops_level);
            return false;
           }
        }
      if(tp > 0.0)
        {
         if(tp >= price)
           {
            reject_reason = StringFormat("Sell TP (%.5f) must be below entry price (%.5f)", tp, price);
            return false;
           }
         if((price - tp) < min_stop_dist)
           {
            reject_reason = StringFormat("Sell TP distance (%.5f) is less than broker stop level (%.5f / %d pts)",
                                         price - tp, min_stop_dist, stops_level);
            return false;
           }
        }
     }

   return true;
  }

//+------------------------------------------------------------------+
//| Calculate Risk-Based Volume matching CMoneyFixedRisk             |
//+------------------------------------------------------------------+
double CRiskProtection::CalculateRiskLot(const string symbol, const ENUM_ORDER_TYPE order_type,
                                        const double price, const double sl, const double risk_percent)
  {
   m_symbol.RefreshRates();
   double minvol = m_symbol.LotsMin();
   double maxvol = m_symbol.LotsMax();
   double stepvol = m_symbol.LotsStep();
   
   if(sl == 0.0 || risk_percent <= 0.0)
      return minvol;

   double loss = 0.0;
   if(price == 0.0)
      loss = -m_account.OrderProfitCheck(symbol, order_type, 1.0, 
                                         (order_type == ORDER_TYPE_BUY ? m_symbol.Ask() : m_symbol.Bid()), sl);
   else
      loss = -m_account.OrderProfitCheck(symbol, order_type, 1.0, price, sl);

   if(loss <= 0.0)
      return minvol;

   double risk_capital = m_account.Balance() * (risk_percent / 100.0);
   double lot = MathFloor(risk_capital / loss / stepvol) * stepvol;
   
   if(lot < minvol)
      lot = minvol;
   if(lot > maxvol)
      lot = maxvol;
      
   return lot;
  }

#endif // __AI_RISK_PROTECTION_MQH__
