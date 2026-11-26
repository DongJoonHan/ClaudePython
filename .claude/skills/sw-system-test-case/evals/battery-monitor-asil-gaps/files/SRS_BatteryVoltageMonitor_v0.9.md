# SW Requirements — 12V Battery Voltage Monitor (v0.9 draft)

ASIL C (SWR-BVM-004, 005, 006), others QM.

Input: BattVolt_Raw (ADC, 12-bit, 0 ~ 4095 counts, conversion: V = counts × 0.005 V), sampled every 5 ms.
Output: BattState (NORMAL, LOW, CRITICAL, HIGH), DTC_BattLow, DTC_ADC_Fault, SafeStateReq (TRUE/FALSE).

- **SWR-BVM-001** The SW shall compute filtered battery voltage as moving average of the last 8 samples.
- **SWR-BVM-002** BattState shall be NORMAL when filtered voltage is within 11.0 V ~ 15.0 V.
- **SWR-BVM-003** BattState shall transition to LOW when filtered voltage < 11.0 V for at least 500 ms, and return to NORMAL when filtered voltage ≥ 11.5 V for at least 500 ms.
- **SWR-BVM-004** BattState shall transition to CRITICAL when filtered voltage < 9.0 V, and the SW shall set SafeStateReq = TRUE within the fault tolerant time interval.
- **SWR-BVM-005** If BattVolt_Raw is 0 or 4095 counts for 4 consecutive samples, the SW shall set DTC_ADC_Fault and SafeStateReq = TRUE within 50 ms of the first faulty sample.
- **SWR-BVM-006** Once SafeStateReq = TRUE, it shall remain TRUE until the next power cycle.
- **SWR-BVM-007** BattState shall be HIGH when filtered voltage > 15.0 V for at least 1 s.
- **SWR-BVM-008** DTC_BattLow shall be stored when BattState = LOW persists for 10 s.
- **SWR-BVM-009** (non-functional) The monitor shall respond robustly to voltage disturbances.
