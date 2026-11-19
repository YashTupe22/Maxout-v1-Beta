//+------------------------------------------------------------------+
//|                                                 VerifyModel.mq5  |
//|   Load the ONNX model in live MT5 and print one prediction       |
//+------------------------------------------------------------------+
#property copyright "AI trading project"
#property version   "1.00"

#include <AI\AISignal.mqh>

input string InpModel     = "AI\\model.onnx";  // model in Common\Files
input double InpThreshold = 0.55;              // signal threshold
input int    InpBars      = 256;               // history bars for features

void OnStart(void)
  {
   CSymbolInfo symbol;
   symbol.Name(_Symbol);
   if(!symbol.RefreshRates())
     {
      Print("VerifyModel: RefreshRates failed");
      return;
     }

   CAISignal signal;
   signal.ModelFile(InpModel);
   signal.ProbabilityThreshold(InpThreshold);
   signal.FeatureBars(InpBars);

   if(!signal.Init(&symbol,_Period,_Point))
     {
      Print("VerifyModel: signal init failed");
      return;
     }
   if(!signal.ValidationSettings())
     {
      Print("VerifyModel: validation failed (model present?)");
      return;
     }

   int lng=signal.LongCondition();
   int sht=signal.ShortCondition();
   double prob=signal.CurrentProbability();

   PrintFormat("VerifyModel: %s %s prob_up=%.6f long=%d short=%d",
               _Symbol,EnumToString(_Period),prob,lng,sht);
  }
//+------------------------------------------------------------------+
