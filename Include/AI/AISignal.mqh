//+------------------------------------------------------------------+
//|                                                     AISignal.mqh |
//|            ONNX probability signal for the CExpert framework     |
//+------------------------------------------------------------------+
#ifndef __AI_SIGNAL_MQH__
#define __AI_SIGNAL_MQH__

#include <Expert\ExpertSignal.mqh>
#include <AI\Features.mqh>
#include <AI\RiskProtection.mqh>

class CAISignal : public CExpertSignal
  {
protected:
   CFeatureEngine    m_features;
   CRiskProtection   m_risk;
   long              m_onnx;
   string            m_model_file;
   double            m_prob_threshold;
   int               m_bars;
   datetime          m_last_bar;
   bool              m_has_pred;
   double            m_prob_up;
   double            m_last_prob;
   datetime          m_last_telemetry_time;
   bool              m_telemetry;
   string            m_telemetry_file;

   // Session filter settings
   bool              m_session_filter_enable;
   int               m_session_start_hour;
   int               m_session_end_hour;

   // News pause settings
   bool              m_news_filter_enable;
   string            m_news_pause_file;

   bool              LoadModel(void);
   bool              UpdatePrediction(void);
   void              WriteTelemetry(void);
   bool              IsTradeAllowedNow(void);

public:
                     CAISignal(void);
                    ~CAISignal(void);

   void              ModelFile(const string file)             { m_model_file=file; }
   void              ProbabilityThreshold(const double value)  { m_prob_threshold=value; }
   void              FeatureBars(const int bars)              { m_bars=bars; }
   void              Telemetry(const bool enabled)             { m_telemetry=enabled; }
   void              TelemetryFile(const string file)         { m_telemetry_file=file; }
   void              SessionFilter(const bool enabled,const int start_hr=7,const int end_hr=20)
                       { m_session_filter_enable=enabled; m_session_start_hour=start_hr; m_session_end_hour=end_hr; }
   void              NewsFilter(const bool enabled,const string file="AI\\news_pause.json")
                       { m_news_filter_enable=enabled; m_news_pause_file=file; }
   void              ConfigureRisk(const bool enable_spread, const int max_spread,
                                   const bool enable_dd, const double max_dd_pct)
                       {
                        m_risk.ConfigureSpread(enable_spread, max_spread);
                        m_risk.ConfigureDailyDrawdown(enable_dd, max_dd_pct);
                       }
   CRiskProtection  *Risk(void)                                { return &m_risk; }
   double            CurrentProbability(void) const            { return(m_last_prob); }
   void              Heartbeat(void);

   virtual bool      Init(CSymbolInfo *symbol,ENUM_TIMEFRAMES period,double point);
   virtual bool      ValidationSettings(void);
   virtual int       LongCondition(void);
   virtual int       ShortCondition(void);
  };
//+------------------------------------------------------------------+
//| Constructor                                                      |
//+------------------------------------------------------------------+
CAISignal::CAISignal(void) : m_onnx(INVALID_HANDLE),
                             m_model_file("AI\\model.onnx"),
                             m_prob_threshold(0.55),
                             m_bars(256),
                             m_last_bar(0),
                             m_has_pred(false),
                             m_prob_up(0.5),
                             m_last_prob(0.5),
                             m_last_telemetry_time(0),
                             m_telemetry(true),
                             m_telemetry_file("AI\\live_status.json"),
                             m_session_filter_enable(false),
                             m_session_start_hour(7),
                             m_session_end_hour(20),
                             m_news_filter_enable(false),
                             m_news_pause_file("AI\\news_pause.json")
  {
  }
//+------------------------------------------------------------------+
//| Destructor                                                       |
//+------------------------------------------------------------------+
CAISignal::~CAISignal(void)
  {
   if(m_onnx!=INVALID_HANDLE)
     {
      OnnxRelease(m_onnx);
      m_onnx=INVALID_HANDLE;
     }
  }
//+------------------------------------------------------------------+
//| Initialization                                                   |
//+------------------------------------------------------------------+
bool CAISignal::Init(CSymbolInfo *symbol,ENUM_TIMEFRAMES period,double point)
  {
   if(!CExpertSignal::Init(symbol,period,point))
      return(false);

   if(!m_features.Init(symbol.Name(),period))
      return(false);

   if(!m_risk.Init(symbol.Name()))
      return(false);

   return(true);
  }
//+------------------------------------------------------------------+
//| Load ONNX model from Common\Files (shared with Strategy Tester)  |
//+------------------------------------------------------------------+
bool CAISignal::LoadModel(void)
  {
   if(m_onnx!=INVALID_HANDLE)
     {
      OnnxRelease(m_onnx);
      m_onnx=INVALID_HANDLE;
     }

   m_onnx=OnnxCreate(m_model_file,ONNX_COMMON_FOLDER);
   if(m_onnx==INVALID_HANDLE)
     {
      PrintFormat("CAISignal: OnnxCreate('%s') failed, error %d",m_model_file,GetLastError());
      return(false);
     }

   const long in_shape[]={1,CFeatureEngine::FeatureCount()};
   if(!OnnxSetInputShape(m_onnx,0,in_shape))
     {
      PrintFormat("CAISignal: OnnxSetInputShape failed, error %d",GetLastError());
      OnnxRelease(m_onnx);
      m_onnx=INVALID_HANDLE;
      return(false);
     }

   const long out_shape[]={1,2};
   if(!OnnxSetOutputShape(m_onnx,0,out_shape))
     {
      PrintFormat("CAISignal: OnnxSetOutputShape failed, error %d",GetLastError());
      OnnxRelease(m_onnx);
      m_onnx=INVALID_HANDLE;
      return(false);
     }

   PrintFormat("CAISignal: model '%s' loaded",m_model_file);
   return(true);
  }
//+------------------------------------------------------------------+
//| Validation                                                       |
//+------------------------------------------------------------------+
bool CAISignal::ValidationSettings(void)
  {
   if(!CExpertSignal::ValidationSettings())
      return(false);

   if(m_prob_threshold<=0.5 || m_prob_threshold>=1.0)
     {
      Print("CAISignal: probability threshold must be between 0.5 and 1.0");
      return(false);
     }
   if(m_bars<AI_MIN_BARS)
     {
      PrintFormat("CAISignal: FeatureBars must be >= %d",AI_MIN_BARS);
      return(false);
     }
   if(!FileIsExist(m_model_file,FILE_COMMON))
     {
      PrintFormat("CAISignal: model not found in Common\\Files: '%s'",m_model_file);
      return(false);
     }
   return(true);
  }
//+------------------------------------------------------------------+
//| Compute prediction once per closed bar                           |
//+------------------------------------------------------------------+
bool CAISignal::UpdatePrediction(void)
  {
   datetime bar=iTime(m_symbol.Name(),m_period,1);
   if(bar==m_last_bar && m_has_pred)
      return(true);

   if(m_onnx==INVALID_HANDLE && !LoadModel())
      return(false);

   if(m_features.Load(m_bars)<=0)
     {
      Print("CAISignal: not enough history for features");
      return(false);
     }

   double features[];
   if(!m_features.Compute(1,features))
      return(false);

   matrixf x(1,CFeatureEngine::FeatureCount());
   for(int i=0; i<CFeatureEngine::FeatureCount(); i++)
      x[0][i]=(float)features[i];

   vectorf output(2);
   if(!OnnxRun(m_onnx,ONNX_NO_CONVERSION,x,output))
     {
      PrintFormat("CAISignal: OnnxRun failed, error %d",GetLastError());
      return(false);
     }

   m_prob_up=(double)output[1];
   m_last_prob=m_prob_up;
   m_last_bar=bar;
   m_has_pred=true;
   WriteTelemetry();
   return(true);
  }
//+------------------------------------------------------------------+
//| Heartbeat: update telemetry on ticks even between bars           |
//+------------------------------------------------------------------+
void CAISignal::Heartbeat(void)
  {
   if(!m_telemetry || MQLInfoInteger(MQL_TESTER))
      return;
   datetime now=TimeCurrent();
   // Write live heartbeat at most once every 5 seconds
   if(now-m_last_telemetry_time>=5)
     {
      WriteTelemetry();
     }
  }

//+------------------------------------------------------------------+
//| Write live telemetry for the dashboard (common folder)           |
//+------------------------------------------------------------------+
void CAISignal::WriteTelemetry(void)
  {
   if(!m_telemetry || MQLInfoInteger(MQL_TESTER))
      return;
   m_last_telemetry_time=TimeCurrent();

   string signal="HOLD";
   if(m_prob_up>=m_prob_threshold)
      signal="BUY";
   else
      if(m_prob_up<=1.0-m_prob_threshold)
         signal="SELL";

   string position="FLAT";
   double lots=0.0;
   if(PositionSelect(m_symbol.Name()))
     {
      lots=PositionGetDouble(POSITION_VOLUME);
      position=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? "LONG" : "SHORT");
     }

   string model=m_model_file;
   StringReplace(model,"\\","/");

   string json=StringFormat(
                 "{\"updated\":\"%s\",\"symbol\":\"%s\",\"period\":\"%s\",\"model\":\"%s\","
                 "\"threshold\":%.2f,\"prob_up\":%.6f,\"signal\":\"%s\",\"bar_time\":\"%s\","
                 "\"close\":%.5f,\"position\":\"%s\",\"lots\":%.2f,\"balance\":%.2f,"
                 "\"equity\":%.2f,\"margin_free\":%.2f,\"spread_pts\":%d,\"max_spread_pts\":%d,"
                 "\"circuit_breaker\":%s,\"daily_drawdown_pct\":%.2f,\"daily_start_equity\":%.2f}",
                 TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
                 m_symbol.Name(),
                 EnumToString((ENUM_TIMEFRAMES)m_period),
                 model,
                 m_prob_threshold,
                 m_prob_up,
                 signal,
                 TimeToString(m_last_bar,TIME_DATE|TIME_MINUTES),
                 m_symbol.Bid(),
                 position,
                 lots,
                 AccountInfoDouble(ACCOUNT_BALANCE),
                 AccountInfoDouble(ACCOUNT_EQUITY),
                 AccountInfoDouble(ACCOUNT_MARGIN_FREE),
                 m_risk.CurrentSpreadPoints(),
                 m_risk.MaxSpreadPoints(),
                 m_risk.IsCircuitBreakerActive() ? "true" : "false",
                 m_risk.DailyDrawdownPct(),
                 m_risk.DailyStartEquity());

   int handle=FileOpen(m_telemetry_file,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE)
      return;
   FileWriteString(handle,json);
   FileClose(handle);
  }
//+------------------------------------------------------------------+
//| Check session, news, and risk filters                            |
//+------------------------------------------------------------------+
bool CAISignal::IsTradeAllowedNow(void)
  {
   // 1. Risk Protection Checks (Spread Filter & Daily Drawdown Circuit Breaker)
   string risk_reason = "";
   if(!m_risk.ValidateNewOrder(risk_reason))
     {
      // Reason logged inside ValidateNewOrder
      return false;
     }

   // 2. Session Filter (broker server / local hour check)
   if(m_session_filter_enable)
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(),dt);
      if(m_session_start_hour <= m_session_end_hour)
        {
         if(dt.hour < m_session_start_hour || dt.hour >= m_session_end_hour)
            return(false);
        }
      else
        {
         // Over midnight session (e.g., 22 to 06)
         if(dt.hour < m_session_start_hour && dt.hour >= m_session_end_hour)
            return(false);
        }
     }

   // 3. News Pause Filter
   if(m_news_filter_enable && FileIsExist(m_news_pause_file,FILE_COMMON))
     {
      int h=FileOpen(m_news_pause_file,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(h!=INVALID_HANDLE)
        {
         string content=FileReadString(h);
         FileClose(h);
         // content format expected: {"no_trade_until": 1732029600} or similar timestamp
         int pos=StringFind(content,"\"no_trade_until\":");
         if(pos>=0)
           {
            string sub=StringSubstr(content,pos+17);
            long until_ts=(long)StringToInteger(sub);
            if(until_ts>(long)TimeCurrent())
               return(false);
           }
        }
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Long signal: model probability of an up move                     |
//+------------------------------------------------------------------+
int CAISignal::LongCondition(void)
  {
   if(!IsTradeAllowedNow())
      return(0);
   if(!UpdatePrediction())
      return(0);
   if(m_prob_up>=m_prob_threshold)
      return(100);
   return(0);
  }
//+------------------------------------------------------------------+
//| Short signal: model probability of a down move                   |
//+------------------------------------------------------------------+
int CAISignal::ShortCondition(void)
  {
   if(!IsTradeAllowedNow())
      return(0);
   if(!UpdatePrediction())
      return(0);
   if(m_prob_up<=(1.0-m_prob_threshold))
      return(100);
   return(0);
  }

#endif // __AI_SIGNAL_MQH__
