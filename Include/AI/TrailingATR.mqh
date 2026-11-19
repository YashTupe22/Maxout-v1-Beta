//+------------------------------------------------------------------+
//|                                                  TrailingATR.mqh |
//|                   ATR-based Dynamic Trailing Stop for CExpert    |
//+------------------------------------------------------------------+
#ifndef __AI_TRAILING_ATR_MQH__
#define __AI_TRAILING_ATR_MQH__

#include <Expert\ExpertTrailing.mqh>

class CTrailingATR : public CExpertTrailing
  {
protected:
   int               m_h_atr;
   int               m_atr_period;
   double            m_atr_mult;
   bool              m_breakeven_enable;
   double            m_breakeven_trigger_atr;
   double            m_breakeven_lock_points;
   double            m_atr[];

public:
                     CTrailingATR(void);
                    ~CTrailingATR(void);

   void              AtrPeriod(const int period)              { m_atr_period=period; }
   void              AtrMultiplier(const double mult)         { m_atr_mult=mult; }
   void              Breakeven(const bool enable)             { m_breakeven_enable=enable; }
   void              BreakevenTrigger(const double atr_mult)  { m_breakeven_trigger_atr=atr_mult; }
   void              BreakevenLock(const double points)       { m_breakeven_lock_points=points; }

   virtual bool      Init(CSymbolInfo *symbol,ENUM_TIMEFRAMES period,double point);
   virtual bool      InitIndicators(CIndicators *indicators);
   virtual bool      ValidationSettings(void);
   virtual bool      CheckTrailingStopLong(CPositionInfo *position,double &sl,double &tp);
   virtual bool      CheckTrailingStopShort(CPositionInfo *position,double &sl,double &tp);
  };

//+------------------------------------------------------------------+
//| Constructor                                                      |
//+------------------------------------------------------------------+
CTrailingATR::CTrailingATR(void) : m_h_atr(INVALID_HANDLE),
                                   m_atr_period(14),
                                   m_atr_mult(2.0),
                                   m_breakeven_enable(true),
                                   m_breakeven_trigger_atr(1.5),
                                   m_breakeven_lock_points(10.0)
  {
  }

//+------------------------------------------------------------------+
//| Destructor                                                       |
//+------------------------------------------------------------------+
CTrailingATR::~CTrailingATR(void)
  {
   if(m_h_atr!=INVALID_HANDLE)
     {
      IndicatorRelease(m_h_atr);
      m_h_atr=INVALID_HANDLE;
     }
  }

//+------------------------------------------------------------------+
//| Initialization                                                   |
//+------------------------------------------------------------------+
bool CTrailingATR::Init(CSymbolInfo *symbol,ENUM_TIMEFRAMES period,double point)
  {
   if(!CExpertTrailing::Init(symbol,period,point))
      return(false);

   m_h_atr=iATR(m_symbol.Name(),m_period,m_atr_period);
   if(m_h_atr==INVALID_HANDLE)
     {
      PrintFormat("CTrailingATR: iATR handle failed, error %d",GetLastError());
      return(false);
     }
   ArraySetAsSeries(m_atr,true);
   return(true);
  }

//+------------------------------------------------------------------+
//| Indicator binding                                                |
//+------------------------------------------------------------------+
bool CTrailingATR::InitIndicators(CIndicators *indicators)
  {
   return(true);
  }

//+------------------------------------------------------------------+
//| Settings validation                                              |
//+------------------------------------------------------------------+
bool CTrailingATR::ValidationSettings(void)
  {
   if(!CExpertTrailing::ValidationSettings())
      return(false);
   if(m_atr_period<=1)
     {
      Print("CTrailingATR: ATR period must be > 1");
      return(false);
     }
   if(m_atr_mult<=0.0)
     {
      Print("CTrailingATR: ATR multiplier must be > 0.0");
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Trailing stop check for long position                            |
//+------------------------------------------------------------------+
bool CTrailingATR::CheckTrailingStopLong(CPositionInfo *position,double &sl,double &tp)
  {
   if(position==NULL)
      return(false);

   if(CopyBuffer(m_h_atr,0,1,1,m_atr)<=0)
      return(false);

   double cur_atr=m_atr[0];
   if(cur_atr<=0.0)
      return(false);

   double open_price=position.PriceOpen();
   double cur_sl=position.StopLoss();
   double bid=m_symbol.Bid();
   double trail_distance=cur_atr*m_atr_mult;
   double target_sl=NormalizeDouble(bid-trail_distance,m_symbol.Digits());

   // Breakeven logic
   if(m_breakeven_enable)
     {
      double be_trigger=open_price+(cur_atr*m_breakeven_trigger_atr);
      if(bid>=be_trigger)
        {
         double be_sl=NormalizeDouble(open_price+(m_breakeven_lock_points*m_adjusted_point),m_symbol.Digits());
         if(target_sl<be_sl)
            target_sl=be_sl;
        }
     }

   // Update SL only if higher than current SL (or if current SL is 0) and below bid
   if(target_sl>cur_sl && target_sl<bid)
     {
      sl=target_sl;
      tp=position.TakeProfit();
      return(true);
     }

   return(false);
  }

//+------------------------------------------------------------------+
//| Trailing stop check for short position                           |
//+------------------------------------------------------------------+
bool CTrailingATR::CheckTrailingStopShort(CPositionInfo *position,double &sl,double &tp)
  {
   if(position==NULL)
      return(false);

   if(CopyBuffer(m_h_atr,0,1,1,m_atr)<=0)
      return(false);

   double cur_atr=m_atr[0];
   if(cur_atr<=0.0)
      return(false);

   double open_price=position.PriceOpen();
   double cur_sl=position.StopLoss();
   double ask=m_symbol.Ask();
   double trail_distance=cur_atr*m_atr_mult;
   double target_sl=NormalizeDouble(ask+trail_distance,m_symbol.Digits());

   // Breakeven logic
   if(m_breakeven_enable)
     {
      double be_trigger=open_price-(cur_atr*m_breakeven_trigger_atr);
      if(ask<=be_trigger)
        {
         double be_sl=NormalizeDouble(open_price-(m_breakeven_lock_points*m_adjusted_point),m_symbol.Digits());
         if(target_sl>be_sl)
            target_sl=be_sl;
        }
     }

   // Update SL only if lower than current SL (or if current SL is 0) and above ask
   if((cur_sl==0.0 || target_sl<cur_sl) && target_sl>ask)
     {
      sl=target_sl;
      tp=position.TakeProfit();
      return(true);
     }

   return(false);
  }

#endif // __AI_TRAILING_ATR_MQH__
