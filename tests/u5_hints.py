"""Step 13's hand judgements of the duplicate hint, which `test_core_fold.py` reads."""

# U5 (Step 13): the duplicate hint, judged. One pair per line, keyed on the two
# edition ids as Step 13's hint sweep drew them, judged against SBN's full record
# (read by S4) and Open Library's `/books/<key>.json` (one fetch per pair).
# The rule, applied the same way to every pair: *same* when a field only a full
# record carries agrees — the page count within max(3, 1%), the series, a named
# volume of the same edition; *different* when one disagrees, or the medium does
# (audiobook, multimedia, e-book, a set); *undetermined* when the Open Library
# side carries none of them, which is a verdict the full records cannot reach.
U5_HINTS = {
    'Open Library:OL13534295M~SBN:SBL0676026': ('same', 'pages: 351 p. both, series Colección grandes novelas both'),  # 0 E01
    'SBN:RAV0708340~Open Library:OL4625368M': ('same', 'pages: 301 p. both'),  # 1 E03
    'Open Library:OL17880054M~SBN:PUV0706935': ('same', 'pages: vi, 314 p. both, Norton 1951'),  # 2 E08
    'SBN:TO00369874~Open Library:OL26899528M': ('same', 'pages: 503 p. both'),  # 3 E09
    'Open Library:OL37805811M~SBN:BA10034674': ('undetermined', "no field: the OL record states no pages or series (and SBN's 120 p. is itself doubtful)"),  # 4 E16
    'Open Library:OL6450693M~SBN:UBO3151877': ('same', 'pages: 91 p. both, Reynal & Hitchcock 1943'),  # 5 N02
    'SBN:RMS2563295~Open Library:OL16219320M': ('same', 'pages: 221 p. both, series Nuovi coralli 2 both'),  # 6 N03
    'SBN:URB0651317~Open Library:OL58786029M': ('different', 'pages: 492 p. (Modern Library college editions T 11) against 554'),  # 7 N04
    'SBN:AQ10032873~Open Library:OL58962733M': ('undetermined', 'pages: 250 against 258, Penguin 972 on SBN only: close but outside the tolerance'),  # 8 N06
    '9788806491307~Open Library:OL13944351M': ('same', "pages: 261 p. both; the SBN ISBN edition is Einaudi's 1979 Supercoralli"),  # 9 N07
    '9788866320951~SBN:LI30005852': ('different', "medium: SBN's is a 4-volume set, OL's a 400-page e-book"),  # 10 N08
    '9780140440010~SBN:TO02170554': ('same', 'pages: 365 p. both, series Penguin classics 51 both, Rieu 1946'),  # 11 N23
    'Open Library:OL20196162M~SBN:VEA0139894': ('same', 'series: Colección grandes novelas both, Sudamericana 1967'),  # 12 E01
    '9780393001143~SBN:PBE0097495': ('same', "pages: 314 p. both; OL's ISBN 0393001143 is the Norton Library N114 SBN names"),  # 13 E08
    'SBN:NAP0101213~Open Library:OL13867976M': ('different', 'series: SBN Romanzo Bompiani 22 cm against OL I grandi tascabili 33 paperback'),  # 14 E09
    'SBN:PUV1025309~Open Library:OL24205427M': ('same', 'pages: 456 p. both, Signet'),  # 15 E16
    'Open Library:OL32897247M~SBN:LO11599909': ('different', 'pages: 66 (hardcover) against 125 p.'),  # 16 N02
    'SBN:RML0382709~Open Library:OL14634798M': ('same', 'pages: 205 p. both, Orion 1959'),  # 17 N03
    'SBN:URB0651317~Open Library:OL32157703M': ('undetermined', 'no field: the OL record states no pages or series'),  # 18 N04
    'Open Library:OL62591436M~SBN:BRI0305759': ('undetermined', 'no field: the OL record states no pages or series'),  # 19 N06
    'SBN:RMS0133831~Open Library:OL4034452M': ('same', 'pages: 261 p. both'),  # 20 N07
    'SBN:TO01560215~Open Library:OL24872296M': ('same', 'pages: 402 against 403, Wiedasch translation 1856 both'),  # 21 N23
    'SBN:SBL0108566~Open Library:OL4958874M': ('same', 'pages: 426 p. both, series I narratori di Feltrinelli both'),  # 22 E01
    'SBN:PUV0177040~Open Library:OL24681697M': ('same', 'pages: 533 p. both, series I grandi (tascabili) 33 both'),  # 23 E09
    'SBN:UPG0027813~Open Library:OL20054206M': ('same', 'pages: 542 p. both, Fontana'),  # 24 E16
    'SBN:LO11042213~Open Library:OL17703476M': ('same', 'pages: 93 p. both'),  # 25 N02
    'SBN:UFI0302679~Open Library:OL13901954M': ('same', 'series: I coralli 184 both'),  # 26 N03
    'Open Library:OL19655522M~SBN:PUV0950938': ('same', 'pages: 545 against 546, series Plain literary texts both'),  # 27 N04
    'Open Library:OL37824533M~SBN:IEI0738875': ('same', 'pages: 313 against 314, Harcourt Brace 1949'),  # 28 N06
    '9788806491307~Open Library:OL13737218M': ('undetermined', 'no field: the OL record states no pages or series'),  # 29 N07
    'SBN:PAV0016382~Open Library:OL6670464M': ('same', 'pages: 452 p. both'),  # 30 N23
    'SBN:LO11684290~9789580439875': ('same', 'pages: 485 against 488, Norma 1997'),  # 31 E01
    'Open Library:OL42955998M~SBN:CSA0158697': ('different', "publisher line and format: SBN's is Fabbri-Bompiani, illustrated, 19 cm; OL's title says 1st edition"),  # 32 E09
    'SBN:BVE0330526~Open Library:OL15250235M': ('same', 'pages: 566 p. both'),  # 33 E16
    'SBN:MOD1574814~Open Library:OL32897247M': ('different', 'pages: 123 p. against 66'),  # 34 N02
    'SBN:LO10092623~Open Library:OL52756471M': ('same', 'pages: 197 p. both, series Biblioteca Leone Ginzburg 3 both'),  # 35 N03
    'SBN:URB0651317~Open Library:OL43060919M': ('different', 'series: Modern Library college editions T 11 against Modern Library #199'),  # 36 N04
    'Open Library:OL62591432M~SBN:BRI0305759': ('undetermined', 'no field: the OL record states no pages or series'),  # 37 N06
    'SBN:PBE0100781~Open Library:OL13737218M': ('undetermined', 'no field: the OL record states no pages or series'),  # 38 N07
    'SBN:UFI0114777~Open Library:OL16405253M': ('same', "volume: SBN catalogues vol. 9 of the 1967 Twickenham edition OL records as one; the pre-sort read OL's '23' pages, which is its 23 cm"),  # 39 N23
    'Open Library:OL14422686M~SBN:TO00667316': ('same', 'pages: 351 p. both'),  # 40 E01
    'SBN:RMS1665510~Open Library:OL14630792M': ('same', 'pages: 503 p. both'),  # 41 E09
    'Open Library:OL37804419M~SBN:LO11307098': ('same', 'pages: 558 against 559, Pantheon 1958'),  # 42 E16
    'Open Library:OL13933375M~SBN:PA10033836': ('undetermined', 'no field: the OL record states no pages or series'),  # 43 N02
    'SBN:CAM0202884~Open Library:OL52802332M': ('same', 'pages: 221 p. both'),  # 44 N03
    'Open Library:OL44945613M~SBN:PUV0950938': ('same', 'pages: 545 p. both, series Plain literary texts both'),  # 45 N04
    'Open Library:OL58703977M~SBN:IEI0738875': ('different', "pages: 313 against 326, and OL's publisher is Harcourt, Brace & World, a name from 1960"),  # 46 N06
    'SBN:RMR0413305~Open Library:OL13944351M': ('same', 'pages: 261 p. both'),  # 47 N07
    'SBN:PAR1304072~Open Library:OL24165826M': ('same', 'series: Papyrus both, Borel 1897'),  # 48 N23
    'SBN:BVE0917706~Open Library:OL20196162M': ('same', 'series: Colección grandes novelas both'),  # 49 E01
    'SBN:TO01054815~Open Library:OL20415672M': ('different', 'pages: 503 against 442 (OL states 12a ed. con correzioni; another OL record of that statement gives 503)'),  # 50 E09
    'SBN:RML0084655~Open Library:OL16383794M': ('same', 'pages: 710 against 715, within 1%, Feltrinelli 1957'),  # 51 E16
    'Open Library:OL32897247M~SBN:UM10116067': ('undetermined', "pages: SBN's pop-up book 60 p. against OL's 66, outside the tolerance but nothing else to go on"),  # 52 N02
    'SBN:RMS2660669~Open Library:OL13922423M': ('undetermined', 'no field agrees or disagrees: SBN 218 p. with no series, OL Nuovi coralli 2 with no pages'),  # 53 N03
    'Open Library:OL18228848M~SBN:BVE0096292': ('same', "editors: Opul'skaja and Kogan, the Literaturnye pamjatniki edition SBN names"),  # 54 N04
    'Open Library:OL62591431M~SBN:TO00666295': ('undetermined', 'no field: the OL record states no pages or series'),  # 55 N06
    'SBN:RCA0574087~Open Library:OL13737218M': ('undetermined', 'no field: the OL record states no pages or series'),  # 56 N07
    'SBN:BVEE004338~Open Library:OL18400912M': ('same', 'pages: [238] leaves both, Louvain 1535'),  # 57 N23
    'Open Library:OL17456146M~SBN:URB0071715': ('same', 'series: Colección grandes novelas both'),  # 58 E01
    'SBN:TO00369874~Open Library:OL20415672M': ('different', 'pages: 503 against 442'),  # 59 E09
    'Open Library:OL20035476M~SBN:BVE0379172': ('same', 'volume: SBN catalogues vol. 2 (p. 299-634) of the 1959 SEIM edition'),  # 60 E16
    'Open Library:OL32897247M~SBN:LO11337183': ('different', "medium: SBN's is an audiobook, 2 CD"),  # 61 N02
    'SBN:RAV0143767~Open Library:OL43761056M': ('same', 'pages: 231 p. both, series Letture per la scuola media 24 both'),  # 62 N03
    'SBN:URB0651317~Open Library:OL43249202M': ('undetermined', 'no field: the OL record states no pages or series'),  # 63 N04
    'Open Library:OL62592233M~SBN:BRI0305759': ('undetermined', 'no field: the OL record states no pages or series'),  # 64 N06
    'SBN:PBE0100781~Open Library:OL4034452M': ('same', 'pages: 261 p. both'),  # 65 N07
    'Open Library:OL17292190M~SBN:LO11129163': ('same', 'pages: 753 p. both, series Tusculum-Bücherei both'),  # 66 N23
    'SBN:FER0099901~Open Library:OL16546099M': ('different', 'pages: 533 against 503 (I grandi tascabili 33)'),  # 67 E09
    'Open Library:OL37804401M~SBN:LO11307098': ('same', 'pages: 558 against 559, Pantheon 1958'),  # 68 E16
    '9788845266324~Open Library:OL32897247M': ('different', "medium: SBN's is a book with 2 CDs, 122 p., with an ISBN"),  # 69 N02
    'SBN:LO10092623~Open Library:OL57424584M': ('same', 'pages: 197 p. both, series Biblioteca Leone Ginzburg 3 both'),  # 70 N03
    'Open Library:OL17522801M~SBN:BVE0278271': ('same', 'pages: 585 p. both'),  # 71 N04
    'Open Library:OL13708884M~SBN:RCA0885048': ('undetermined', 'no field agrees or disagrees: OL Oscar 454 with no pages, SBN 341 p. with no series'),  # 72 N06
    'SBN:CFI0850471~Open Library:OL13944351M': ('same', 'pages: 261 p. both'),  # 73 N07
    'Open Library:OL13642410M~SBN:TO02170554': ('undetermined', 'no field: the OL record states no pages or series'),  # 74 N23
    'SBN:RMS2798381~Open Library:OL20415672M': ('different', 'pages: 503 against 442'),  # 75 E09
    'SBN:RCA0765089~Open Library:OL26982034M': ('same', 'pages: 713 p. both'),  # 76 E16
    'Open Library:OL22306145M~SBN:PA10033836': ('undetermined', 'no field: the OL record states no pages or series'),  # 77 N02
    'SBN:LO10887205~Open Library:OL21940728M': ('same', 'pages: 157 p. both, Collier 1961'),  # 78 N03
    'Open Library:OL4371422M~SBN:BVE0096292': ('same', 'pages: 808 p. both, series Literaturnye pamjatniki both'),  # 79 N04
    'Open Library:OL6049335M~SBN:IEI0738875': ('same', 'pages: 313 against 314'),  # 80 N06
    'SBN:TO01580290~Open Library:OL13737218M': ('undetermined', 'no field: the OL record states no pages or series'),  # 81 N07
    'SBN:UFI0094217~Open Library:OL5591356M': ('same', 'volume: SBN catalogues vol. 10 of the 1967 Twickenham edition OL records as 2 v.'),  # 82 N23
    'SBN:RLZ0142687~Open Library:OL16546099M': ('different', 'pages: 533 against 503 (I grandi tascabili 33)'),  # 83 E09
    'Open Library:OL19876391M~SBN:USM1812505': ('same', 'volume: SBN catalogues vol. 1 (p. 9-297) of the 1959 SEIM edition OL records as 2 v.'),  # 84 E16
    'SBN:LO11042213~Open Library:OL44983527M': ('same', 'pages: 93 p. both'),  # 85 N02
    'SBN:SBL0485399~Open Library:OL13922423M': ('different', 'series: SBN Saggi 232 against OL Nuovi coralli 2'),  # 86 N03
    'Open Library:OL62592368M~SBN:BRI0305759': ('undetermined', 'no field: the OL record states no pages or series'),  # 87 N06
    '9788806491307~Open Library:OL4034452M': ('same', 'pages: 261 p. both'),  # 88 N07
    'SBN:TO01560215~Open Library:OL24759753M': ('same', 'pages: 402 against 403'),  # 89 N23
    'SBN:TO01054815~Open Library:OL3271967M': ('different', 'pages: 503 against 442'),  # 90 E09
    '9783436005856~SBN:PUV1047641': ('undetermined', 'no field: the OL record states no pages or series'),  # 91 E16
    '9788845267604~Open Library:OL32897247M': ('undetermined', "no field agrees or disagrees: SBN's pop-up states no pages, OL states 66"),  # 92 N02
    'Open Library:OL19042911M~SBN:RLZ0103050': ('different', "content: SBN's volume is Se questo è un uomo with La tregua, 325 p., against 221 p."),  # 93 N03
    'Open Library:OL24976268M~SBN:BRI0305759': ('undetermined', 'no field: the OL record states no pages or series'),  # 94 N06
    'SBN:LIA0170775~Open Library:OL13737218M': ('undetermined', 'no field: the OL record states no pages or series'),  # 95 N07
    'SBN:RAV0174294~Open Library:OL4597284M': ('same', 'pages: 405 p. both, series Oscar 154 both'),  # 96 N23
    'SBN:RLZ0272363~Open Library:OL13867976M': ('same', 'pages: 533 p. both, series I grandi tascabili 33 both'),  # 97 E09
    'Open Library:OL6247150M~SBN:LO11307098': ('same', 'pages: 558 against 559'),  # 98 E16
    'Open Library:OL6516576M~SBN:LIA0593183': ('same', 'pages: 93 p. both'),  # 99 N02
}
