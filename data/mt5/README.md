# MT5 Data Files

Place the six CSV files in this directory using these exact names:

- XAUUSD_M1_202501020105_202607131322.csv
- XAUUSD_M5_202501020105_202607131320.csv
- XAUUSD_M15_202501020100_202607131315.csv
- XAUUSD_H1_202501020100_202607131300.csv
- XAUUSD_H4_202501020000_202607131200.csv
- XAUUSD_D1_202501020000_202607130000.csv

The original `Daily` file is represented as canonical timeframe `D1`. The D1 importer must assign `00:00:00` when the `<TIME>` column is absent.
