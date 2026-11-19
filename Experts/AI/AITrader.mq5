//+------------------------------------------------------------------+
//|                                                     AITrader.mq5 |
//|             ONNX model + CExpert framework trading robot          |
//+------------------------------------------------------------------+
#property copyright "AI trading project"
#property version   "1.00"

#include <Expert\Expert.mqh>
#include <AI\AISignal.mqh>
#include <AI\TrailingATR.mqh>
#include <Expert\Trailing\TrailingNone.mqh>
#include <Expert\Money\MoneyFixedRisk.mqh>

//--- expert inputs
input string Inp_Expert_Title       ="AITrader";       // expert title
input int    Inp_MagicNumber        =20261119;         // magic number
input bool   Inp_EveryTick          =false;            // process every tick

//--- AI signal inputs
input string Inp_AI_Model           ="AI\\model.onnx"; // model under Common\Files
input double Inp_AI_Threshold       =0.55;             // probability threshold
input int    Inp_AI_Bars            =256;              // history bars for features (also covers H4/D1 MTF lookback)
input bool   Inp_AI_Telemetry       =true;             // write live status JSON for dashboard

//--- filter inputs
input bool   Inp_Session_Filter     =true;             // Enable trading session filter
input int    Inp_Session_Start_Hour =7;                // Session start hour (0-23)
input int    Inp_Session_End_Hour   =20;               // Session end hour (0-23)
input bool   Inp_News_Filter        =false;            // Enable news pause filter

//--- trade inputs
input int    Inp_TP_Pips            =60;               // Take Profit (in pips)
input int    Inp_SL_Pips            =30;               // Stop Loss (in pips)
input double Inp_Risk_Percent       =1.0;              // Risk per trade (% of equity)

//--- risk & protection inputs
input bool   Inp_EnableMaxSpread    =true;             // Enable maximum spread protection
input int    Inp_MaxSpreadPoints    =30;               // Maximum permitted spread (points)
input bool   Inp_EnableDailyLoss    =true;             // Enable daily drawdown limit
input double Inp_MaxDailyDDPct      =3.0;              // Maximum daily drawdown (% of start equity)

//--- trailing inputs
input bool   Inp_Trailing_Enable    =true;             // Enable dynamic ATR trailing
input double Inp_Trailing_ATR_Mult  =2.0;              // Trailing stop distance in ATR
input bool   Inp_Breakeven_Enable   =true;             // Move SL to breakeven when in profit
input double Inp_Breakeven_Trigger  =1.5;              // Breakeven trigger distance in ATR
input double Inp_Breakeven_Lock_Pts =10.0;             // Points locked above/below entry at breakeven

//+------------------------------------------------------------------+
//| Global expert object                                             |
//+------------------------------------------------------------------+
CExpert    ExtExpert;
CAISignal *ExtSignal=NULL;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit(void)
  {
   if(!ExtExpert.Init(Symbol(),Period(),Inp_EveryTick,Inp_MagicNumber))
     {
      PrintFormat("%s: expert init failed",__FUNCTION__);
      ExtExpert.Deinit();
      return(-1);
     }

//--- create AI signal
   CAISignal *signal=new CAISignal;
   if(signal==NULL)
     {
      PrintFormat("%s: cannot create signal",__FUNCTION__);
      ExtExpert.Deinit();
      return(-2);
     }
   ExtSignal=signal;

//--- parameters required before InitSignal()
   signal.ModelFile(Inp_AI_Model);
   signal.ProbabilityThreshold(Inp_AI_Threshold);
   signal.FeatureBars(Inp_AI_Bars);
   signal.Telemetry(Inp_AI_Telemetry);
   signal.SessionFilter(Inp_Session_Filter,Inp_Session_Start_Hour,Inp_Session_End_Hour);
   signal.NewsFilter(Inp_News_Filter);
   signal.ConfigureRisk(Inp_EnableMaxSpread, Inp_MaxSpreadPoints, Inp_EnableDailyLoss, Inp_MaxDailyDDPct);

   if(!ExtExpert.InitSignal(signal))
     {
      PrintFormat("%s: signal init failed",__FUNCTION__);
      ExtExpert.Deinit();
      return(-3);
     }

//--- TP/SL for the signal
// PriceLevelUnit() in CExpert is m_adjusted_point = 10 * point on 3/5 digits = 1 pip.
// Passing Inp_TP_Pips directly aligns 1:1 with pips across all symbols.
   signal.TakeLevel(Inp_TP_Pips);
   signal.StopLevel(Inp_SL_Pips);

   if(!signal.ValidationSettings())
     {
      PrintFormat("%s: signal parameters invalid",__FUNCTION__);
      ExtExpert.Deinit();
      return(-4);
     }

//--- trailing stop configuration
   if(Inp_Trailing_Enable)
     {
      CTrailingATR *trailing_atr=new CTrailingATR;
      if(trailing_atr==NULL)
        {
         PrintFormat("%s: cannot create ATR trailing",__FUNCTION__);
         ExtExpert.Deinit();
         return(-5);
        }
      trailing_atr.AtrMultiplier(Inp_Trailing_ATR_Mult);
      trailing_atr.Breakeven(Inp_Breakeven_Enable);
      trailing_atr.BreakevenTrigger(Inp_Breakeven_Trigger);
      trailing_atr.BreakevenLock(Inp_Breakeven_Lock_Pts);

      if(!ExtExpert.InitTrailing(trailing_atr))
        {
         PrintFormat("%s: ATR trailing init failed",__FUNCTION__);
         ExtExpert.Deinit();
         return(-6);
        }
      if(!trailing_atr.ValidationSettings())
        {
         PrintFormat("%s: ATR trailing parameters invalid",__FUNCTION__);
         ExtExpert.Deinit();
         return(-7);
        }
     }
   else
     {
      CTrailingNone *trailing=new CTrailingNone;
      if(trailing==NULL)
        {
         PrintFormat("%s: cannot create trailing",__FUNCTION__);
         ExtExpert.Deinit();
         return(-5);
        }
      if(!ExtExpert.InitTrailing(trailing))
        {
         PrintFormat("%s: trailing init failed",__FUNCTION__);
         ExtExpert.Deinit();
         return(-6);
        }
      if(!trailing.ValidationSettings())
        {
         PrintFormat("%s: trailing parameters invalid",__FUNCTION__);
         ExtExpert.Deinit();
         return(-7);
        }
     }

//--- fixed-fractional risk sizing
   CMoneyFixedRisk *money=new CMoneyFixedRisk;
   if(money==NULL)
     {
      PrintFormat("%s: cannot create money manager",__FUNCTION__);
      ExtExpert.Deinit();
      return(-8);
     }
   if(!ExtExpert.InitMoney(money))
     {
      PrintFormat("%s: money init failed",__FUNCTION__);
      ExtExpert.Deinit();
      return(-9);
     }
   money.Percent(Inp_Risk_Percent);
   if(!money.ValidationSettings())
     {
      PrintFormat("%s: money parameters invalid",__FUNCTION__);
      ExtExpert.Deinit();
      return(-10);
     }

//--- indicators
   if(!ExtExpert.InitIndicators())
     {
      PrintFormat("%s: indicator init failed",__FUNCTION__);
      ExtExpert.Deinit();
      return(-11);
     }

   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   ExtExpert.Deinit();
   ExtSignal=NULL;
  }
//+------------------------------------------------------------------+
//| Tick handler                                                     |
//+------------------------------------------------------------------+
void OnTick(void)
  {
   ExtExpert.OnTick();
   if(ExtSignal!=NULL)
      ExtSignal.Heartbeat();
  }
//+------------------------------------------------------------------+
//| Trade handler                                                    |
//+------------------------------------------------------------------+
void OnTrade(void)
  {
   ExtExpert.OnTrade();
  }
//+------------------------------------------------------------------+
//| Timer handler                                                    |
//+------------------------------------------------------------------+
void OnTimer(void)
  {
   ExtExpert.OnTimer();
  }
//+------------------------------------------------------------------+
