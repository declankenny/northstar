# Currency catalog: contents

Status: approved on November 4, 2026 and built in migration `0010_currencies` (#125). This lists what it loads; the migration is the source of truth, and this is not the spec. Generated from the SIX ISO 4217 "list one" file, published 2026-09-17 (https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml). Names are ISO's own, unchanged. The migration would be generated from the same file, not typed by hand.

The file has 178 distinct codes. **155 are included** and 23 excluded.

## Rule

Include a code when ISO marks it as a currency and not a fund, and it has 0, 2 or 3 minor units. Withdrawn (historic) codes are not in this file and are not included. None of the included codes is a duplicate: a code shared by several countries (EUR, USD, XOF) is one row.

## 0 minor units (16)

| Code | Name | ISO number |
| --- | --- | --- |
| BIF | Burundi Franc | 108 |
| CLP | Chilean Peso | 152 |
| DJF | Djibouti Franc | 262 |
| GNF | Guinean Franc | 324 |
| ISK | Iceland Krona | 352 |
| JPY | Yen | 392 |
| KMF | Comorian Franc | 174 |
| KRW | Won | 410 |
| PYG | Guarani | 600 |
| RWF | Rwanda Franc | 646 |
| UGX | Uganda Shilling | 800 |
| VND | Dong | 704 |
| VUV | Vatu | 548 |
| XAF | CFA Franc BEAC | 950 |
| XOF | CFA Franc BCEAO | 952 |
| XPF | CFP Franc | 953 |

## 2 minor units (132)

| Code | Name | ISO number |
| --- | --- | --- |
| AED | UAE Dirham | 784 |
| AFN | Afghani | 971 |
| ALL | Lek | 008 |
| AMD | Armenian Dram | 051 |
| AOA | Kwanza | 973 |
| ARS | Argentine Peso | 032 |
| AUD | Australian Dollar | 036 |
| AWG | Aruban Florin | 533 |
| AZN | Azerbaijan Manat | 944 |
| BAM | Convertible Mark | 977 |
| BBD | Barbados Dollar | 052 |
| BDT | Taka | 050 |
| BMD | Bermudian Dollar | 060 |
| BND | Brunei Dollar | 096 |
| BOB | Boliviano | 068 |
| BRL | Brazilian Real | 986 |
| BSD | Bahamian Dollar | 044 |
| BTN | Ngultrum | 064 |
| BWP | Pula | 072 |
| BYN | Belarusian Ruble | 933 |
| BZD | Belize Dollar | 084 |
| CAD | Canadian Dollar | 124 |
| CDF | Congolese Franc | 976 |
| CHF | Swiss Franc | 756 |
| CNY | Yuan Renminbi | 156 |
| COP | Colombian Peso | 170 |
| CRC | Costa Rican Colon | 188 |
| CUP | Cuban Peso | 192 |
| CVE | Cabo Verde Escudo | 132 |
| CZK | Czech Koruna | 203 |
| DKK | Danish Krone | 208 |
| DOP | Dominican Peso | 214 |
| DZD | Algerian Dinar | 012 |
| EGP | Egyptian Pound | 818 |
| ERN | Nakfa | 232 |
| ETB | Ethiopian Birr | 230 |
| EUR | Euro | 978 |
| FJD | Fiji Dollar | 242 |
| FKP | Falkland Islands Pound | 238 |
| GBP | Pound Sterling | 826 |
| GEL | Lari | 981 |
| GHS | Ghana Cedi | 936 |
| GIP | Gibraltar Pound | 292 |
| GMD | Dalasi | 270 |
| GTQ | Quetzal | 320 |
| GYD | Guyana Dollar | 328 |
| HKD | Hong Kong Dollar | 344 |
| HNL | Lempira | 340 |
| HTG | Gourde | 332 |
| HUF | Forint | 348 |
| IDR | Rupiah | 360 |
| ILS | New Israeli Sheqel | 376 |
| INR | Indian Rupee | 356 |
| IRR | Iranian Rial | 364 |
| JMD | Jamaican Dollar | 388 |
| KES | Kenyan Shilling | 404 |
| KGS | Som | 417 |
| KHR | Riel | 116 |
| KPW | North Korean Won | 408 |
| KYD | Cayman Islands Dollar | 136 |
| KZT | Tenge | 398 |
| LAK | Lao Kip | 418 |
| LBP | Lebanese Pound | 422 |
| LKR | Sri Lanka Rupee | 144 |
| LRD | Liberian Dollar | 430 |
| LSL | Loti | 426 |
| MAD | Moroccan Dirham | 504 |
| MDL | Moldovan Leu | 498 |
| MGA | Malagasy Ariary | 969 |
| MKD | Denar | 807 |
| MMK | Kyat | 104 |
| MNT | Tugrik | 496 |
| MOP | Pataca | 446 |
| MRU | Ouguiya | 929 |
| MUR | Mauritius Rupee | 480 |
| MVR | Rufiyaa | 462 |
| MWK | Malawi Kwacha | 454 |
| MXN | Mexican Peso | 484 |
| MYR | Malaysian Ringgit | 458 |
| MZN | Mozambique Metical | 943 |
| NAD | Namibia Dollar | 516 |
| NGN | Naira | 566 |
| NIO | Cordoba Oro | 558 |
| NOK | Norwegian Krone | 578 |
| NPR | Nepalese Rupee | 524 |
| NZD | New Zealand Dollar | 554 |
| PAB | Balboa | 590 |
| PEN | Sol | 604 |
| PGK | Kina | 598 |
| PHP | Philippine Peso | 608 |
| PKR | Pakistan Rupee | 586 |
| PLN | Zloty | 985 |
| QAR | Qatari Rial | 634 |
| RON | Romanian Leu | 946 |
| RSD | Serbian Dinar | 941 |
| RUB | Russian Ruble | 643 |
| SAR | Saudi Riyal | 682 |
| SBD | Solomon Islands Dollar | 090 |
| SCR | Seychelles Rupee | 690 |
| SDG | Sudanese Pound | 938 |
| SEK | Swedish Krona | 752 |
| SGD | Singapore Dollar | 702 |
| SHP | Saint Helena Pound | 654 |
| SLE | Leone | 925 |
| SOS | Somali Shilling | 706 |
| SRD | Surinam Dollar | 968 |
| SSP | South Sudanese Pound | 728 |
| STN | Dobra | 930 |
| SVC | El Salvador Colon | 222 |
| SYP | Syrian Pound | 760 |
| SZL | Lilangeni | 748 |
| THB | Baht | 764 |
| TJS | Somoni | 972 |
| TMT | Turkmenistan New Manat | 934 |
| TOP | Pa’anga | 776 |
| TRY | Turkish Lira | 949 |
| TTD | Trinidad and Tobago Dollar | 780 |
| TWD | New Taiwan Dollar | 901 |
| TZS | Tanzanian Shilling | 834 |
| UAH | Hryvnia | 980 |
| USD | US Dollar | 840 |
| UYU | Peso Uruguayo | 858 |
| UZS | Uzbekistan Sum | 860 |
| VED | Bolívar Soberano | 926 |
| VES | Bolívar Soberano | 928 |
| WST | Tala | 882 |
| XCD | East Caribbean Dollar | 951 |
| XCG | Caribbean Guilder | 532 |
| YER | Yemeni Rial | 886 |
| ZAR | Rand | 710 |
| ZMW | Zambian Kwacha | 967 |
| ZWG | Zimbabwe Gold | 924 |

## 3 minor units (7)

| Code | Name | ISO number |
| --- | --- | --- |
| BHD | Bahraini Dinar | 048 |
| IQD | Iraqi Dinar | 368 |
| JOD | Jordanian Dinar | 400 |
| KWD | Kuwaiti Dinar | 414 |
| LYD | Libyan Dinar | 434 |
| OMR | Rial Omani | 512 |
| TND | Tunisian Dinar | 788 |

## Excluded: funds (10)

Fund codes are not money held in an account.

| Code | Name | Minor units |
| --- | --- | --- |
| BOV | Mvdol | 2 |
| CHE | WIR Euro | 2 |
| CHW | WIR Franc | 2 |
| CLF | Unidad de Fomento | 4 |
| COU | Unidad de Valor Real | 2 |
| MXV | Mexican Unidad de Inversion (UDI) | 2 |
| USN | US Dollar (Next day) | 2 |
| UYI | Uruguay Peso en Unidades Indexadas (UI) | 0 |
| UYW | Unidad Previsional | 4 |
| XAD | Arab Accounting Dinar | 2 |

## Excluded: metals, units of account and special codes (13)

No minor unit, and not a currency a household holds.

| Code | Name |
| --- | --- |
| XAG | Silver |
| XAU | Gold |
| XBA | Bond Markets Unit European Composite Unit (EURCO) |
| XBB | Bond Markets Unit European Monetary Unit (E.M.U.-6) |
| XBC | Bond Markets Unit European Unit of Account 9 (E.U.A.-9) |
| XBD | Bond Markets Unit European Unit of Account 17 (E.U.A.-17) |
| XDR | SDR (Special Drawing Right) |
| XPD | Palladium |
| XPT | Platinum |
| XSU | Sucre |
| XTS | Codes specifically reserved for testing purposes |
| XUA | ADB Unit of Account |
| XXX | The codes assigned for transactions where no currency is involved |

## Points to decide

- **Names (decided).** Keep ISO's names exactly as they are. They are short and sometimes only the unit ("Yen", "Won", "Rand", "Sol"), so the picker, which matches on code and name, finds nothing for "japan" or "south africa". A country column from the same file can be added later if that proves annoying.
- **Territorial codes.** XAF, XOF, XPF and XCD are real currencies shared by several countries, so they are included.
- **Codes in dispute or in flux.** Some included currencies are unusual to hold (KPW, SYP, CUP, VES, VED). ISO lists them, so I include them rather than judge.
- **Fund exclusion.** CLF and UYW are excluded as funds and also have 4 decimals, which the table's `minor_units` check does not allow.
