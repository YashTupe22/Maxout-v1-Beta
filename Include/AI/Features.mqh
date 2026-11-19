//+------------------------------------------------------------------+
//|                                                     Features.mqh |
//|                          AI trading project - feature engine     |
//+------------------------------------------------------------------+
#ifndef __AI_FEATURES_MQH__
#define __AI_FEATURES_MQH__

// Feature vector layout (must match python/train_onnx.py):
// --- Primary timeframe (m_period) ---
// 0 ret1        1 ret3        2 ret5        3 ret10       4 ret20
// 5 rsi         6 macd        7 macd_sig    8 bb_up_dist  9 bb_low_dist
// 10 bb_mid_dist 11 atr_rel   12 stoch_k    13 stoch_d    14 adx
// 15 di_diff    16 cci        17 range_atr  18 body_range 19 hour_sin
// 20 hour_cos
// --- H4 context features ---
// 21 h4_rsi     22 h4_atr_rel  23 h4_adx    24 h4_ret1   25 h4_bb_mid_dist
// --- D1 context features ---
// 26 d1_rsi     27 d1_atr_rel  28 d1_adx    29 d1_ret1
#define AI_FEATURE_COUNT 30
#define AI_MIN_BARS      (AI_FEATURE_COUNT+120)

class CFeatureEngine
  {
protected:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_period;
   int               m_count;
   // --- Primary TF handles ---
   int               m_h_atr;
   int               m_h_rsi;
   int               m_h_macd;
   int               m_h_bands;
   int               m_h_stoch;
   int               m_h_adx;
   int               m_h_cci;
   // --- H4 handles ---
   int               m_h4_rsi;
   int               m_h4_atr;
   int               m_h4_adx;
   int               m_h4_bands;
   // --- D1 handles ---
   int               m_d1_rsi;
   int               m_d1_atr;
   int               m_d1_adx;

   // --- Primary TF buffers ---
   MqlRates          m_rates[];
   double            m_atr[];
   double            m_rsi[];
   double            m_macd[];
   double            m_macdsig[];
   double            m_bbmid[];
   double            m_bbup[];
   double            m_bblow[];
   double            m_stoch[];
   double            m_stochd[];
   double            m_adx[];
   double            m_plusdi[];
   double            m_minusdi[];
   double            m_cci[];
   // --- H4 buffers ---
   MqlRates          m_h4_rates[];
   double            m_h4_rsi_buf[];
   double            m_h4_atr_buf[];
   double            m_h4_adx_buf[];
   double            m_h4_bands_mid[];
   // --- D1 buffers ---
   MqlRates          m_d1_rates[];
   double            m_d1_rsi_buf[];
   double            m_d1_atr_buf[];
   double            m_d1_adx_buf[];

public:
                     CFeatureEngine(void);
                    ~CFeatureEngine(void);

   static int        FeatureCount(void) { return(AI_FEATURE_COUNT); }
   static void       FeatureNames(string &names[]);

   bool              Init(const string symbol,const ENUM_TIMEFRAMES period);
   void              Deinit(void);
   int               Load(const int wanted);
   int               Count(void) const { return(m_count); }
   bool              Compute(const int shift,double &features[]) const;

   datetime          TimeAt(const int shift) const;
   double            CloseAt(const int shift) const;
  };

//+------------------------------------------------------------------+
//| Constructor                                                      |
//+------------------------------------------------------------------+
CFeatureEngine::CFeatureEngine(void) : m_symbol(""),
                                       m_period(PERIOD_CURRENT),
                                       m_count(0),
                                       m_h_atr(INVALID_HANDLE),
                                       m_h_rsi(INVALID_HANDLE),
                                       m_h_macd(INVALID_HANDLE),
                                       m_h_bands(INVALID_HANDLE),
                                       m_h_stoch(INVALID_HANDLE),
                                       m_h_adx(INVALID_HANDLE),
                                       m_h_cci(INVALID_HANDLE),
                                       m_h4_rsi(INVALID_HANDLE),
                                       m_h4_atr(INVALID_HANDLE),
                                       m_h4_adx(INVALID_HANDLE),
                                       m_h4_bands(INVALID_HANDLE),
                                       m_d1_rsi(INVALID_HANDLE),
                                       m_d1_atr(INVALID_HANDLE),
                                       m_d1_adx(INVALID_HANDLE)
  {
  }
//+------------------------------------------------------------------+
//| Destructor                                                       |
//+------------------------------------------------------------------+
CFeatureEngine::~CFeatureEngine(void)
  {
   Deinit();
  }
//+------------------------------------------------------------------+
//| Feature names (CSV header order)                                 |
//+------------------------------------------------------------------+
void CFeatureEngine::FeatureNames(string &names[])
  {
   string tmp[AI_FEATURE_COUNT]=
     {
      // Primary TF (indices 0-20)
      "ret1","ret3","ret5","ret10","ret20",
      "rsi","macd","macd_sig","bb_up_dist","bb_low_dist",
      "bb_mid_dist","atr_rel","stoch_k","stoch_d","adx",
      "di_diff","cci","range_atr","body_range","hour_sin","hour_cos",
      // H4 context (indices 21-25)
      "h4_rsi","h4_atr_rel","h4_adx","h4_ret1","h4_bb_mid_dist",
      // D1 context (indices 26-29)
      "d1_rsi","d1_atr_rel","d1_adx","d1_ret1"
     };
   ArrayResize(names,AI_FEATURE_COUNT);
   for(int i=0; i<AI_FEATURE_COUNT; i++)
      names[i]=tmp[i];
  }
//+------------------------------------------------------------------+
//| Create indicator handles                                         |
//+------------------------------------------------------------------+
bool CFeatureEngine::Init(const string symbol,const ENUM_TIMEFRAMES period)
  {
   Deinit();
   m_symbol=symbol;
   m_period=period;

   // --- Primary TF ---
   m_h_atr  =iATR(symbol,period,14);
   m_h_rsi  =iRSI(symbol,period,14,PRICE_CLOSE);
   m_h_macd =iMACD(symbol,period,12,26,9,PRICE_CLOSE);
   m_h_bands=iBands(symbol,period,20,0,2.0,PRICE_CLOSE);
   m_h_stoch=iStochastic(symbol,period,14,3,3,MODE_SMA,STO_LOWHIGH);
   m_h_adx  =iADX(symbol,period,14);
   m_h_cci  =iCCI(symbol,period,20,PRICE_TYPICAL);

   if(m_h_atr==INVALID_HANDLE || m_h_rsi==INVALID_HANDLE || m_h_macd==INVALID_HANDLE ||
      m_h_bands==INVALID_HANDLE || m_h_stoch==INVALID_HANDLE || m_h_adx==INVALID_HANDLE ||
      m_h_cci==INVALID_HANDLE)
     {
      PrintFormat("CFeatureEngine: primary TF indicator creation failed, error %d",GetLastError());
      Deinit();
      return(false);
     }

   // --- H4 ---
   m_h4_rsi  =iRSI(symbol,PERIOD_H4,14,PRICE_CLOSE);
   m_h4_atr  =iATR(symbol,PERIOD_H4,14);
   m_h4_adx  =iADX(symbol,PERIOD_H4,14);
   m_h4_bands=iBands(symbol,PERIOD_H4,20,0,2.0,PRICE_CLOSE);

   if(m_h4_rsi==INVALID_HANDLE || m_h4_atr==INVALID_HANDLE ||
      m_h4_adx==INVALID_HANDLE || m_h4_bands==INVALID_HANDLE)
     {
      PrintFormat("CFeatureEngine: H4 indicator creation failed, error %d",GetLastError());
      Deinit();
      return(false);
     }

   // --- D1 ---
   m_d1_rsi=iRSI(symbol,PERIOD_D1,14,PRICE_CLOSE);
   m_d1_atr=iATR(symbol,PERIOD_D1,14);
   m_d1_adx=iADX(symbol,PERIOD_D1,14);

   if(m_d1_rsi==INVALID_HANDLE || m_d1_atr==INVALID_HANDLE || m_d1_adx==INVALID_HANDLE)
     {
      PrintFormat("CFeatureEngine: D1 indicator creation failed, error %d",GetLastError());
      Deinit();
      return(false);
     }

   return(true);
  }
//+------------------------------------------------------------------+
//| Release handles                                                  |
//+------------------------------------------------------------------+
void CFeatureEngine::Deinit(void)
  {
   // Primary TF
   if(m_h_atr!=INVALID_HANDLE)   { IndicatorRelease(m_h_atr);   m_h_atr=INVALID_HANDLE;   }
   if(m_h_rsi!=INVALID_HANDLE)   { IndicatorRelease(m_h_rsi);   m_h_rsi=INVALID_HANDLE;   }
   if(m_h_macd!=INVALID_HANDLE)  { IndicatorRelease(m_h_macd);  m_h_macd=INVALID_HANDLE;  }
   if(m_h_bands!=INVALID_HANDLE) { IndicatorRelease(m_h_bands); m_h_bands=INVALID_HANDLE; }
   if(m_h_stoch!=INVALID_HANDLE) { IndicatorRelease(m_h_stoch); m_h_stoch=INVALID_HANDLE; }
   if(m_h_adx!=INVALID_HANDLE)   { IndicatorRelease(m_h_adx);   m_h_adx=INVALID_HANDLE;   }
   if(m_h_cci!=INVALID_HANDLE)   { IndicatorRelease(m_h_cci);   m_h_cci=INVALID_HANDLE;   }
   // H4
   if(m_h4_rsi!=INVALID_HANDLE)   { IndicatorRelease(m_h4_rsi);   m_h4_rsi=INVALID_HANDLE;   }
   if(m_h4_atr!=INVALID_HANDLE)   { IndicatorRelease(m_h4_atr);   m_h4_atr=INVALID_HANDLE;   }
   if(m_h4_adx!=INVALID_HANDLE)   { IndicatorRelease(m_h4_adx);   m_h4_adx=INVALID_HANDLE;   }
   if(m_h4_bands!=INVALID_HANDLE) { IndicatorRelease(m_h4_bands); m_h4_bands=INVALID_HANDLE; }
   // D1
   if(m_d1_rsi!=INVALID_HANDLE)   { IndicatorRelease(m_d1_rsi);   m_d1_rsi=INVALID_HANDLE;   }
   if(m_d1_atr!=INVALID_HANDLE)   { IndicatorRelease(m_d1_atr);   m_d1_atr=INVALID_HANDLE;   }
   if(m_d1_adx!=INVALID_HANDLE)   { IndicatorRelease(m_d1_adx);   m_d1_adx=INVALID_HANDLE;   }
   m_count=0;
  }
//+------------------------------------------------------------------+
//| Load history and indicator buffers (index 0 = oldest)            |
//+------------------------------------------------------------------+
int CFeatureEngine::Load(const int wanted)
  {
   m_count=0;
   int available=Bars(m_symbol,m_period);
   if(available<=0)
      return(0);

   m_count=(int)MathMin(wanted,available);
   if(m_count<AI_MIN_BARS)
      return(0);

   // --- Primary TF ---
   if(CopyRates(m_symbol,m_period,0,m_count,m_rates)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_atr,0,0,m_count,m_atr)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_rsi,0,0,m_count,m_rsi)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_macd,0,0,m_count,m_macd)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_macd,1,0,m_count,m_macdsig)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_bands,0,0,m_count,m_bbmid)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_bands,1,0,m_count,m_bbup)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_bands,2,0,m_count,m_bblow)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_stoch,0,0,m_count,m_stoch)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_stoch,1,0,m_count,m_stochd)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_adx,0,0,m_count,m_adx)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_adx,1,0,m_count,m_plusdi)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_adx,2,0,m_count,m_minusdi)!=m_count)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h_cci,0,0,m_count,m_cci)!=m_count)
     { m_count=0; return(0); }

   // --- H4: always load at least 30 bars ---
   int h4_load=MathMax(30,Bars(m_symbol,PERIOD_H4));
   h4_load=MathMin(h4_load,Bars(m_symbol,PERIOD_H4));
   if(h4_load<3)
     { m_count=0; return(0); }
   if(CopyRates(m_symbol,PERIOD_H4,0,h4_load,m_h4_rates)!=h4_load)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h4_rsi,0,0,h4_load,m_h4_rsi_buf)!=h4_load)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h4_atr,0,0,h4_load,m_h4_atr_buf)!=h4_load)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h4_adx,0,0,h4_load,m_h4_adx_buf)!=h4_load)
     { m_count=0; return(0); }
   if(CopyBuffer(m_h4_bands,0,0,h4_load,m_h4_bands_mid)!=h4_load)
     { m_count=0; return(0); }

   // --- D1: always load at least 30 bars ---
   int d1_load=MathMax(30,Bars(m_symbol,PERIOD_D1));
   d1_load=MathMin(d1_load,Bars(m_symbol,PERIOD_D1));
   if(d1_load<3)
     { m_count=0; return(0); }
   if(CopyRates(m_symbol,PERIOD_D1,0,d1_load,m_d1_rates)!=d1_load)
     { m_count=0; return(0); }
   if(CopyBuffer(m_d1_rsi,0,0,d1_load,m_d1_rsi_buf)!=d1_load)
     { m_count=0; return(0); }
   if(CopyBuffer(m_d1_atr,0,0,d1_load,m_d1_atr_buf)!=d1_load)
     { m_count=0; return(0); }
   if(CopyBuffer(m_d1_adx,0,0,d1_load,m_d1_adx_buf)!=d1_load)
     { m_count=0; return(0); }

   return(m_count);
  }
//+------------------------------------------------------------------+
//| Time of the bar at 'shift' bars back from the current bar        |
//+------------------------------------------------------------------+
datetime CFeatureEngine::TimeAt(const int shift) const
  {
   int j=m_count-1-shift;
   if(j<0 || j>=m_count)
      return(0);
   return(m_rates[j].time);
  }
//+------------------------------------------------------------------+
//| Close of the bar at 'shift' bars back from the current bar       |
//+------------------------------------------------------------------+
double CFeatureEngine::CloseAt(const int shift) const
  {
   int j=m_count-1-shift;
   if(j<0 || j>=m_count)
      return(0.0);
   return(m_rates[j].close);
  }
//+------------------------------------------------------------------+
//| Compute feature vector for the bar 'shift' bars back             |
//+------------------------------------------------------------------+
bool CFeatureEngine::Compute(const int shift,double &features[]) const
  {
   if(m_count<=0)
      return(false);
   int j=m_count-1-shift;
   if(j-20<0 || j>=m_count)
      return(false);

   double c=m_rates[j].close;
   if(c<=0.0)
      return(false);

   double atr=m_atr[j];
   if(atr<=0.0)
      return(false);

   if(ArraySize(features)!=AI_FEATURE_COUNT)
      ArrayResize(features,AI_FEATURE_COUNT);

   // ---- Primary TF features [0..20] ----
   features[0] =MathLog(c/m_rates[j-1].close);
   features[1] =MathLog(c/m_rates[j-3].close);
   features[2] =MathLog(c/m_rates[j-5].close);
   features[3] =MathLog(c/m_rates[j-10].close);
   features[4] =MathLog(c/m_rates[j-20].close);

   features[5] =m_rsi[j]/100.0;
   features[6] =m_macd[j]/atr;
   features[7] =m_macdsig[j]/atr;
   features[8] =(m_bbup[j]-c)/atr;
   features[9] =(c-m_bblow[j])/atr;
   features[10]=(c-m_bbmid[j])/atr;
   features[11]=atr/c;
   features[12]=m_stoch[j]/100.0;
   features[13]=m_stochd[j]/100.0;
   features[14]=m_adx[j]/100.0;
   features[15]=(m_plusdi[j]-m_minusdi[j])/100.0;
   features[16]=m_cci[j]/100.0;

   double hi=m_rates[j].high;
   double lo=m_rates[j].low;
   double op=m_rates[j].open;
   double range=hi-lo;
   if(range<=0.0)
      range=atr;

   features[17]=range/atr;
   features[18]=(c-op)/range;

   MqlDateTime dt;
   TimeToStruct(m_rates[j].time,dt);
   double angle=2.0*M_PI*(double)dt.hour/24.0;
   features[19]=MathSin(angle);
   features[20]=MathCos(angle);

   // ---- H4 context features [21..25] ----
   // CopyBuffer/CopyRates with index 0 = most recent bar
   // m_h4_rates[0] = current/most-recent H4 bar; [1] = previous, [2] = bar before that
   int h4_sz=ArraySize(m_h4_rates);
   if(h4_sz<3)
      return(false);

   double h4_c   =m_h4_rates[1].close;   // last completed H4 bar close
   double h4_atr =m_h4_atr_buf[1];
   if(h4_c<=0.0 || h4_atr<=0.0)
      return(false);

   // [21] h4_rsi: RSI(14) on H4 / 100.0
   features[21]=m_h4_rsi_buf[1]/100.0;

   // [22] h4_atr_rel: ATR(14) on H4 / H4 close
   features[22]=h4_atr/h4_c;

   // [23] h4_adx: ADX(14) on H4 / 100.0
   features[23]=m_h4_adx_buf[1]/100.0;

   // [24] h4_ret1: log(H4_close[1] / H4_close[2])  (prev completed bar / bar before that)
   double h4_c2=m_h4_rates[2].close;
   if(h4_c2<=0.0)
      return(false);
   features[24]=MathLog(h4_c/h4_c2);

   // [25] h4_bb_mid_dist: (H4_close - H4_BB_mid) / H4_ATR
   features[25]=(h4_c-m_h4_bands_mid[1])/h4_atr;

   // ---- D1 context features [26..29] ----
   int d1_sz=ArraySize(m_d1_rates);
   if(d1_sz<3)
      return(false);

   double d1_c   =m_d1_rates[1].close;   // last completed D1 bar close
   double d1_atr =m_d1_atr_buf[1];
   if(d1_c<=0.0 || d1_atr<=0.0)
      return(false);

   // [26] d1_rsi: RSI(14) on D1 / 100.0
   features[26]=m_d1_rsi_buf[1]/100.0;

   // [27] d1_atr_rel: ATR(14) on D1 / D1 close
   features[27]=d1_atr/d1_c;

   // [28] d1_adx: ADX(14) on D1 / 100.0
   features[28]=m_d1_adx_buf[1]/100.0;

   // [29] d1_ret1: log(D1_close[1] / D1_close[2])
   double d1_c2=m_d1_rates[2].close;
   if(d1_c2<=0.0)
      return(false);
   features[29]=MathLog(d1_c/d1_c2);

   // ---- Clamp all features to [-5, 5] and NaN-guard ----
   for(int k=0; k<AI_FEATURE_COUNT; k++)
     {
      if(!MathIsValidNumber(features[k]))
         return(false);
      if(features[k]>5.0)
         features[k]=5.0;
      else
         if(features[k]<-5.0)
            features[k]=-5.0;
     }
   return(true);
  }

#endif // __AI_FEATURES_MQH__
