@echo off
title Flight Price Tracker
echo Starting Flight Price Tracker...
cd /d "C:\Users\admin\.gemini\antigravity\scratch\bank_statement_extractor"
python track_prices.py
echo.
echo Process complete. Flight price history updated in:
echo C:\Users\admin\.gemini\antigravity\scratch\bank_statement_extractor\output\flight_price_history.xlsx
echo.
pause
