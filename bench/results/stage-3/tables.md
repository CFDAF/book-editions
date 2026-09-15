### Rules, pooled over the eight books

| rule | collisions (both ISBN) | TP | FP | precision | truth pairs | recall | recall, same-year truth | truth pairs reached once colliding rows are fetched | OL editions with a true SBN duplicate · merged with one · only wrong | unverifiable (SBN lacks · OL lacks · both) | fetches needed (OL has ISBN) / all | saving |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| primary | 125 | 82 | 43 | 0.656 | 499 | 0.164 | 82/130 = 0.631 | 166/499 | 201 · 78 · 31 | 25 · 45 · 218 | 146 (105) / 778 | 0.812 |
| exact publisher | 110 | 73 | 37 | 0.664 | 499 | 0.146 | 73/130 = 0.562 | 155/499 | 201 · 70 · 27 | 19 · 44 · 206 | 129 (90) / 778 | 0.834 |
| OL language missing matches | 162 | 103 | 59 | 0.636 | 499 | 0.206 | 103/130 = 0.792 | 201/499 | 201 · 97 · 41 | 28 · 55 · 250 | 174 (131) / 778 | 0.776 |


### Per book, primary rule

| book | SBN rows · with ISBN | OL editions · with ISBN · with language | truth pairs (same year) | distinct shared ISBNs | collisions (both ISBN) | TP | FP | precision | recall | unverifiable | fetches needed / all | SBN–SBN collisions (sharing an ISBN) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N19 | 7 · 7 | 17 · 17 · 13 | 4 (3) | 3 | 0 | 0 | 0 | — | 0.0 | 0 | 0 / 7 | 1 (0) |
| E02 | 26 · 16 | 14 · 12 · 12 | 2 (2) | 1 | 2 | 2 | 0 | 1.0 | 1.0 | 0 | 1 / 26 | 0 (0) |
| N14 | 48 · 45 | 40 · 40 · 34 | 12 (8) | 9 | 7 | 6 | 1 | 0.857 | 0.5 | 0 | 6 / 48 | 11 (7) |
| N08 | 57 · 50 | 40 · 40 · 21 | 32 (11) | 14 | 10 | 5 | 5 | 0.5 | 0.156 | 0 | 6 / 57 | 3 (1) |
| N01 | 109 · 72 | 81 · 78 · 68 | 113 (26) | 22 | 20 | 15 | 5 | 0.75 | 0.133 | 0 | 14 / 109 | 73 (7) |
| E01 | 143 · 84 | 208 · 169 · 162 | 93 (28) | 27 | 29 | 20 | 9 | 0.69 | 0.215 | 8 | 26 / 143 | 58 (6) |
| N06 | 172 · 128 | 537 · 465 · 374 | 73 (30) | 38 | 38 | 17 | 21 | 0.447 | 0.233 | 13 | 34 / 172 | 43 (6) |
| N10 | 216 · 81 | 468 · 332 · 413 | 170 (22) | 20 | 19 | 17 | 2 | 0.895 | 0.1 | 267 | 59 / 216 | 198 (10) |


### False positives involving a record that is not a plain edition (judgements.STAGE3)

| record | false-positive pairs |
|---|---|
| E01 /books/OL45606013M: edition record with a foreign ISBN | 1 |
| N06 VIA0214939: not the book | 2 |
| N06 TO10037839: not the book | 1 |
| N06 TO02081267: volume with other works | 1 |


### Why true duplicates do not collide (primary rule, pairs)

| components that differ | pairs |
|---|---|
| year differs | 224 |
| language missing + year differs | 48 |
| language differs + year differs | 39 |
| language missing + year differs + publisher differs | 25 |
| year differs + publisher differs | 23 |
| language missing | 21 |
| publisher differs | 19 |
| year missing + publisher differs | 6 |
| language missing + publisher differs | 5 |
| language differs + publisher differs | 2 |
| language differs | 1 |
| language differs + year differs + publisher differs | 1 |
| year missing | 1 |
| year differs + publisher missing | 1 |
| year missing + publisher missing | 1 |


### Shape of the ISBN truth

| book | OL editions joined to several SBN records | SBN records joined to several OL editions | language differs | year differs | largest ISBN cluster (SBN × OL = pairs) | resting only on an annotated SBN ISBN |
|---|---|---|---|---|---|---|
| N19 | 1 | 1 | 0 | 1 | 9781529115543: 2 × 1 = 2 | 0 |
| E02 | 0 | 1 | 0 | 0 | 9780810204478: 1 × 2 = 2 | 0 |
| N14 | 1 | 1 | 0 | 4 | 9780156007757: 1 × 3 = 3 | (pbk.) 3 |
| N08 | 6 | 9 | 0 | 21 | 9788866320326: 6 × 2 = 12 | ediz. 13, 2020 1 |
| N01 | 10 | 42 | 37 | 87 | 9788845906862: 31 × 2 = 62 | Paperback ed. 1; Rist. 2009 1; recuperato da catalogo editor. 1 |
| E01 | 11 | 23 | 1 | 63 | 9788437604947: 5 × 4 = 20 | 0 |
| N06 | 8 | 12 | 0 | 43 | 9788804507451: 10 × 1 = 10 | rist. 1 |
| N10 | 10 | 32 | 5 | 142 | 9782070360024: 23 × 5 = 115 | stampa 1985 2; Rist. 1973 1; stampa 1990 5; Rist. 2007 2; Rist. 1978 2 |


### Full-record fetches (mobile gateway, one at a time, cold)

| book | rows | fetched | first-pass problems | wall s | requests | failed | retries (urllib3) | bogus BID control |
|---|---|---|---|---|---|---|---|---|
| N19 | 7 | 7 | 0 | 1.5 | 8 | 0 | 0 | mismatch: asked ZZQ9999999, got None |
| E02 | 26 | 26 | 0 | 7.2 | 27 | 0 | 0 | mismatch: asked ZZQ9999999, got None |
| N14 | 48 | 48 | 0 | 20.5 | 49 | 0 | 0 | mismatch: asked ZZQ9999999, got None |
| N08 | 57 | 57 | 0 | 11.7 | 58 | 0 | 0 | mismatch: asked ZZQ9999999, got None |
| N01 | 109 | 109 | 0 | 25.3 | 110 | 0 | 0 | mismatch: asked ZZQ9999999, got None |
| E01 | 143 | 143 | 0 | 42.4 | 144 | 0 | 0 | mismatch: asked ZZQ9999999, got None |
| N06 | 172 | 172 | 0 | 43.0 | 173 | 0 | 0 | mismatch: asked ZZQ9999999, got None |
| N10 | 216 | 216 | 0 | 102.3 | 217 | 0 | ProtocolError×1 | mismatch: asked ZZQ9999999, got None |


### Requests per host

| host | requests | failed | total s | median of per-book p50 s | max s | retries |
|---|---|---|---|---|---|---|
| opac.sbn.it/opacmobilegw | 786 | 0 | 251.69 | 0.221 | 2.198 | ProtocolError×1 |


### Same-work records outside the listings (Stage 2, found by today's routes)

| book · class | distinct records |
|---|---|
| E01 · not linked to W | 47 |
| E01 · separate OL work record | 4 |
| E02 · not linked to W | 7 |
| E02 · separate OL work record | 4 |
| N01 · not linked to W | 4 |
| N06 · not linked to W | 42 |
| N06 · separate OL work record | 5 |
| N08 · not linked to W | 4 |
| N10 · separate OL work record | 2 |
| N14 · not linked to W | 6 |
| N14 · separate OL work record | 3 |
| N19 · not linked to W | 1 |
