//+------------------------------------------------------------------+
//|                                               ExportFeatures.mq5 |
//|        Export AI features + forward label to Models (CSV)        |
//+------------------------------------------------------------------+
#property copyright "AI trading project"
#property version   "1.00"

#include <AI\Features.mqh>

input int    InpBars     = 20000;  // bars of history to export
input int    InpHorizon  = 5;      // predicted horizon in bars
input string InpFileName = "";     // CSV path under MQL5\Files (empty = auto)

//+------------------------------------------------------------------+
//| Script entry point                                               |
//+------------------------------------------------------------------+
void OnStart(void)
  {
   if(InpHorizon<1)
     {
      Print("InpHorizon must be >= 1");
      return;
     }

   CFeatureEngine features;
   if(!features.Init(_Symbol,_Period))
     {
      Print("ExportFeatures: feature engine init failed");
      return;
     }

   int wanted=(int)MathMin(InpBars,Bars(_Symbol,_Period));
   int loaded=features.Load(wanted);
   if(loaded<=0)
     {
      PrintFormat("ExportFeatures: not enough history (need >= %d bars)",AI_MIN_BARS);
      return;
     }

   string file=InpFileName;
   if(file=="")
      file=StringFormat("AI\\features_%s_%s.csv",_Symbol,EnumToString(_Period));

   int handle=FileOpen(file,FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("ExportFeatures: cannot create '%s', error %d",file,GetLastError());
      return;
     }

   string names[];
   CFeatureEngine::FeatureNames(names);

   string header="time";
   for(int i=0; i<CFeatureEngine::FeatureCount(); i++)
      header+=","+names[i];
   header+=",fwd,label";
   FileWrite(handle,header);

   double row[];
   int rows=0,ups=0,downs=0;

   for(int shift=InpHorizon+1; shift+20<loaded; shift++)
     {
      if(!features.Compute(shift,row))
         continue;

      double close_now=features.CloseAt(shift);
      double close_future=features.CloseAt(shift-InpHorizon);
      if(close_now<=0.0 || close_future<=0.0)
         continue;

      double fwd=MathLog(close_future/close_now);
      int label=(fwd>0.0 ? 1 : 0);

      string line=TimeToString(features.TimeAt(shift),TIME_DATE|TIME_MINUTES);
      for(int k=0; k<CFeatureEngine::FeatureCount(); k++)
         line+=","+DoubleToString(row[k],10);
      line+=","+DoubleToString(fwd,10)+","+IntegerToString(label);
      FileWrite(handle,line);

      rows++;
      if(label==1)
         ups++;
      else
         downs++;
     }

   FileClose(handle);

   PrintFormat("ExportFeatures: %d rows (%d up / %d down), horizon %d, saved to '%s'",
               rows,ups,downs,InpHorizon,file);
  }
//+------------------------------------------------------------------+
