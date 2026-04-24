# NYgrid Bus to NYISO Node Mapping

Maps each of the 46 NYgrid buses (35 unique names in Vatic) to the closest NYISO published LMP reference point.

## Mapping Table

| Bus Name | Zone | Method | NYISO Reference | Note |
|----------|:----:|--------|-----------------|------|
| AK-3 | J | zonal | Zone J (N.Y.C.) | Arthur Kill; use N.Y.C. avg |
| ALBANY | F | nodal | PTID [23571, 23572] | ALBANY___1/2 |
| BINGHAMTON | C | nodal | PTID [23790] | BINGHAMTON___COGEN (zone E node used for zone C bus) |
| BUCHANAN | G | zonal | Zone G (HUD VL) | Indian Point area; use HUD VL avg |
| CE UG | I | nodal | PTID [24194] | CE_DUNWOOD___DRP |
| CLAY | C | zonal | Zone C (CENTRL) | No direct match; use CENTRL avg |
| COLTON | E | zonal | Zone E (MHK VL) | No direct match; use MHK VL avg |
| DUNKIRK | A | nodal | PTID [23563, 23564] | DUNKIRK___1/2 |
| EDIC | E | zonal | Zone E (MHK VL) | No direct match; use MHK VL avg |
| GARDENVILLE | A | nodal | PTID [24039] | GARDENVILLE___LBMP |
| GESONIDGE | C | zonal | Zone C (CENTRL) | No direct match; use CENTRL avg |
| GILBOA | E | nodal | PTID [23756] | GILBOA___1 |
| GOETHALS | J | zonal | Zone J (N.Y.C.) | No direct match; use N.Y.C. avg |
| HILLSIDE | C | zonal | Zone C (CENTRL) | No direct match; use CENTRL avg |
| HUNTLEY | A | nodal | PTID [23557, 23558] | HUNTLEY___63/64 |
| LAPEER | C | zonal | Zone C (CENTRL) | No direct match; use CENTRL avg |
| LEEDS | G | zonal | Zone G (HUD VL) | No direct match; use HUD VL avg |
| MEYER | C | zonal | Zone C (CENTRL) | No direct match; use CENTRL avg |
| MILLWOOD | H | nodal | PTID [24193] | CE_MILLWOOD___DRP |
| MOSES E | D | zonal | Zone D (NORTH) | No direct MOSES match; use NORTH avg |
| MOSES W | E | zonal | Zone E (MHK VL) | No direct match; use MHK VL avg |
| NEW SEATHED | F | zonal | Zone F (CAPITL) | New Scotland substation; use CAPITL avg |
| NIAGARA E | A | nodal | PTID [323715] | NIAGARA_115E_LBMP |
| NIAGARA W | A | nodal | PTID [323714] | NIAGARA_115W_LBMP |
| NORTHPORT | K | nodal | PTID [23551, 23552] | NORTHPORT___1/2 |
| PLATTSBURGH | D | zonal | Zone D (NORTH) | No direct match; use NORTH avg |
| PLEASANT VLY | G | nodal | PTID [24000] | PLEASANTVLY___LBMP |
| PORTER | E | zonal | Zone E (MHK VL) | No direct match; use MHK VL avg |
| RAMAPO | G | nodal | PTID [323565] | RAMAPO___LBMP |
| RAV A-3 | K | zonal | Zone K (LONGIL) | Ravenswood; use LONGIL avg |
| ROCHESTER | B | nodal | PTID [23652] | ROCHESTER_9_IC |
| ROTTERDAM | F | zonal | Zone F (CAPITL) | No direct match; use CAPITL avg |
| STOLLE RD | B | zonal | Zone B (GENESE) | No direct match; use GENESE avg |
| WATERCURE | C | zonal | Zone C (CENTRL) | No direct match; use CENTRL avg |
| WRHL | C | zonal | Zone C (CENTRL) | No direct match; use CENTRL avg |

## Notes

- **Nodal**: Direct substation or generator match in NYISO's published generator-level LBMP data (damlbmp_gen).
- **Zonal**: No direct match; uses zone-average LBMP from NYISO's zonal LBMP data (damlbmp_zone).
- 46 NYgrid buses map to 35 unique names in Vatic's template because multiple buses at the same substation are aggregated.
- NYISO publishes ~560 generator-level nodes; only 17 of 35 model buses have a direct match.
