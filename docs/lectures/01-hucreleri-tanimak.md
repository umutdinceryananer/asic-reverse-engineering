# Ders 1 — Hücreleri tanımak

Ders 0'da tek bir hücrenin içine baktık ve transistörleri gördük. Şimdi bir
adım geri çekiliyoruz: layout'ta 9875 yerleşim var, **her biri hangi hücre?**

Bu dersin sonunda şunları biliyor olacaksın: bir yerleşimin ne olduğunu, hücre
sıralarının neden dönüşümlü ters çevrildiğini, bir hücreyi isminden değil
geometrisinden nasıl tanıyacağını, ve neden bunun **yeterli olmadığını**.

---

## 1. Yerleşim nedir

GDS'te bir kütüphane hücresi **bir kez** çizilir. Layout'ta yüzlerce kez
kullanılır. Her kullanım bir **reference** (yerleşim) kaydıdır ve üç şey söyler:

- hangi hücre
- nereye (koordinat)
- **nasıl döndürülmüş/aynalanmış**

Üçüncüsü kolayca gözden kaçar ama en çok hata çıkaran yer orasıdır. Bu dersin
teknik zorluğunun yarısı bu tek alandan geliyor.

---

## 2. Sıralar neden ters çevriliyor

Ders 0'da her hücrenin altında `VGND`, üstünde `VPWR` rayı olduğunu görmüştük.
Şimdi hücreleri üst üste sıralar halinde dizmemiz gerekiyor.

Hepsini aynı yönde dizersen şöyle olur:

```
   ─── VPWR ───
   sıra 1
   ─── VGND ───
   ─── VPWR ───     ← iki farklı ray yan yana, ikisi de ayrı ayrı çizilmeli
   sıra 0
   ─── VGND ───
```

İki komşu sıranın arasında **iki ayrı ray** var, biri VGND biri VPWR. Yer israfı.

Bir üstteki sırayı ters çevirirsen:

```
   ─── VGND ───     ← paylaşılıyor
   sıra 1  (ters)
   ─── VPWR ───     ← paylaşılıyor
   sıra 0  (düz)
   ─── VGND ───
```

Artık komşu sıralar aynı rayı **paylaşıyor**. Her sınırda bir ray tasarruf
ediyorsun. Yerleştirme araçları bu yüzden sıraları dönüşümlü çevirir.

Warm-up'ın DEF dosyasında bunu doğrudan görebilirsin:

```
ROW ROW_0 unithd 10120 10880 N  DO 173 BY 1 STEP 460 0 ;
ROW ROW_1 unithd 10120 13600 FS DO 173 BY 1 STEP 460 0 ;
ROW ROW_2 unithd 10120 16320 N  DO 173 BY 1 STEP 460 0 ;
ROW ROW_3 unithd 10120 19040 FS DO 173 BY 1 STEP 460 0 ;
```

`N`, `FS`, `N`, `FS` — bir düz bir ters. Ayrıca `STEP 460` ve `DO 173` var:
sıra başına 173 tane 0.460 µm'lik site. Ders 0'daki site genişliği tam burada
karşımıza çıkıyor.

---

## 3. İki farklı yönelim dili

Sorun şu: **GDS ile DEF aynı şeyi farklı anlatıyor.**

GDS şöyle diyor: "önce x ekseninde aynala, sonra şu kadar döndür." İki bilgi
saklıyor: bir `mirror` bayrağı ve bir açı.

DEF ise isim veriyor: `N`, `S`, `FN`, `FS` gibi.

Bu ikisini elle eşleştirmek zorundasın, yoksa her şey kayar. Dönüşümleri kâğıt
üstünde birleştirince tablo şöyle çıkıyor:

| GDS aynala | GDS açı | DEF | Nokta nereye gider |
|---|---|---|---|
| hayır | 0 | `N` | (x, y) |
| hayır | 90 | `W` | (−y, x) |
| hayır | 180 | `S` | (−x, −y) |
| hayır | 270 | `E` | (y, −x) |
| **evet** | 0 | `FS` | (x, −y) |
| **evet** | 90 | `FW` | (y, x) |
| **evet** | 180 | `FN` | (−x, y) |
| **evet** | 270 | `FE` | (−y, −x) |

Satırlardan birini birlikte doğrulayalım, mantığı görmen için. "Aynala, sonra
180° döndür" ne yapar?

1. Aynala: `(x, y) → (x, −y)`
2. 180° döndür: `(x, −y) → (−x, y)`

Sonuç `(x, y) → (−x, y)`, yani **y ekseninde aynalama**. DEF'in buna verdiği
isim `FN`. Tablodaki her satır böyle çıkarılıyor.

Bizim layout'larda sadece `N`, `S`, `FN`, `FS` görünüyor. Mantıklı: sıradaki
hücreler asla 90° döndürülmez, sadece çevrilir.

---

## 4. "Nereye" sorusunun ikinci tuzağı

Yönelimi çözdün diyelim. Bir tuzak daha var, ve bu daha sinsi.

**GDS**, hücrenin kendi orijininin nereye düştüğünü yazar.
**DEF**, yerleştirilmiş hücrenin **sol alt köşesini** yazar.

Hücre düz duruyorsa (`N`) bu ikisi aynı noktadır. Ama ters çevrilmişse değildir:
hücre orijininin altında kalır, sol alt köşe başka yerdedir.

Çözmek için hücrenin ayak izini bilmen gerekiyor. Neyse ki Ders 0'da görmüştük:
`areaid.sc` katmanı (81/4) tam olarak hücrenin resmi sınırını çiziyor. Her
standart hücrede var.

Yaptığımız şey: ayak izinin dört köşesini dönüşümden geçir, sonra en küçük x ve
en küçük y'yi al. Bu, yerleştirilmiş halin sol alt köşesi. Artık DEF ile aynı
dili konuşuyoruz.

Bunu koda döktüm, [tools/stage1_cells.py](../../tools/stage1_cells.py).

---

## 5. Doğrulama: sayı saymak yetmez

Şimdi çıkardığımız listeyi cevap anahtarıyla karşılaştıracağız.

Burada önemli bir metodoloji noktası var. "230 hücre buldum, DEF de 230 diyor,
tamam" demek **yetersiz** bir doğrulama. İki hücreyi birbirine karıştırmış
olabilirim, sayı yine tutar. Ya da hepsini 5 µm kaydırmış olabilirim, sayı yine
tutar.

DEF bize sayı değil **liste** veriyor:

```
- PHY_EDGE_ROW_0_Left_29 sky130_fd_sc_hd__decap_3 + SOURCE DIST + FIXED ( 10120 10880 ) N ;
```

Her satırda instance adı, hücre tipi, konum ve yönelim var. Yani her yerleşimi
**tek tek** doğrulayabiliriz. Eşleştirmeyi konum üzerinden yapıyoruz, çünkü
instance isimleri GDS'e taşınmıyor.

Sonuç:

```
DEF declares 230 components, parsed 230
stage 1 gives 230 instances

exact matches      230/230  (100.00%)
wrong cell type    0
wrong orientation  0
```

230'un 230'u. Tip, konum, yönelim — üçü de. Faz 1'in çıkış kriteri buydu.

Bir ayrıntı: GDS'te 1099 yerleşim var ama DEF 230 diyor. Fark 869 `VIA_*`
hücresi. Bunlar routing via'ları — DEF onları bileşen olarak değil, net
bölümünde tutuyor. Ayıklamak çıkarıcının ilk işi.

---

## 6. Şimdi asıl iş: isimsiz tanıma

Buraya kadar hile yaptık. Hücrelerin isimleri dosyada duruyordu, ben de okudum.
Gerçek bir tersine mühendislikte isim olmaz.

Öyleyse bir hücreyi **sadece geometrisinden** nasıl tanırız?

### Transistörleri saymak

Ders 0'ın en önemli cümlesini hatırla:

> Poly'nin diff'i kestiği her yerde bir transistör vardır.

Bu bir benzetme değil, **hesaplanabilir bir ifade**. İki katmanı alıp
kesişimlerini hesaplarsan (buna boolean AND işlemi deniyor) ve çıkan parçaları
sayarsan, hücredeki transistör sayısını bulursun.

Dahası: bu parçaları bir de `nwell` ile kesiştirirsen, hangilerinin havuzun
içinde kaldığını görürsün — onlar PMOS, kalanlar NMOS.

Yani Ders 0'da gözle yaptığımız şeyin tamamı üç satır koda iniyor. Sonuçlar:

| Hücre | Transistör | Okuma |
|---|---|---|
| `nand2_2` | 8 (4P, 4N) | **Ders 0'da elle saymıştık, tutuyor** |
| `nor2_2` | 8 (4P, 4N) | NAND'ın duali, aynı maliyet |
| `dfrtp_2` | 30 | flip-flop pahalı bir eleman |
| `clkbuf_16` | 40 (20P, 20N) | drive 16, iki poly şekli üzerinde çok parmak |
| `tapvpwrvgnd_1` | 0 | kuyu bağlantısı, cihaz yok |
| `VIA_*` | 0 | sadece routing |
| `INTERNAL_3`, `INTERNAL_7` | 0 | marker hücreleri, devre taşımıyor |

Son satır güzel bir örnek. Ders 0'da bu iki hücrenin devre olmadığını "içinde
diff ve poly katmanı yok" diye çıkarsamıştık. Şimdi bambaşka bir yöntem —
boolean kesişim — aynı cevabı veriyor. **İki bağımsız yol aynı sonuca çıkıyorsa
sonuç doğrudur.** Ders 0'da öğrendiğimiz alışkanlık bu.

### Parmak izi çıkarmak

Transistör saymak tanımaya yetmez (birazdan göreceğiz). Kesin kimlik için
**digest** kullanıyoruz: hücrenin bütün poligonlarını al, sol alt köşesi orijine
gelecek şekilde kaydır, koordinatları veritabanı ızgarasına yuvarla, sırala ve
hash'le.

Kaydırma önemli, çünkü aynı hücre farklı orijinlerle çizilmiş olabilir.
Yuvarlama da önemli, çünkü iki özdeş hücre kayan nokta hatasıyla ayrışmasın.

Peki döndürme? Hücre **tanımları** hiç döndürülmez, sadece yerleşimleri
döndürülür — yani bizim dosyalarımızda buna gerek yok. Yine de parmak izlerini
**sekiz yönelimin hepsi için** indeksliyoruz, çünkü kütüphane döndürülmüş
saklanmış olsaydı da çalışmalı. Bunun bir bedeli var: bir tanım, kütüphanedeki
hücrenin döndürülmüş hali olarak eşleşirse, o yerleşimin gerçek yönelimi ikisinin
**bileşkesi** olur. Sekiz dönüşüm bir grup oluşturduğu için bileşke iyi tanımlı;
kodda 2x2 matris çarpımıyla yapıyorum, çünkü sekiz elemanlı bir grup için elle
yazılmış vaka tablosu sessiz hata üretmenin güvenilir bir yoludur.

### Referans kütüphane

Parmak izini neyle karşılaştıracağız? Cevap: **PDK'nın kendi hücre GDS'leriyle.**
sky130 kütüphanesindeki 437 hücrenin her biri ayrı bir GDS dosyası olarak
yayınlanmış, toplam 4 MB. `tools/fetch_pdk.py` bunları indiriyor.

Bir ayrıntı önemli: indirme **belirli bir commit'e sabitlenmiş**. Sabitlenmezse
kütüphane ileride bir hücreyi yeniden çizdiğinde pipeline'ın neyi tanıdığı
sessizce değişirdi. Tekrar üretilebilirlik iddiası varsa girdiler de sabit
olmalı.

### Test

Yöntem çalışıyor mu? Warm-up'ta 230 yerleşimin **hepsi** yalnızca geometriden
tanındı, ve çıktının en önemli satırı şu:

```
cross check against surviving hierarchy names
  every geometric identification matches the name in the layout
```

Yani geometriden verdiğimiz her isim, dosyadaki isimle aynı. İki hedefte toplam
1848 yerleşim, sıfır uyuşmazlık.

---

## 6b. Gerçek dünyadan bir sürpriz: PDK sürüm kayması

Puzzle'da çalıştırınca 22 yerleşim eşleşmedi. Ama `INTERNAL_*` gibi sahte
hücreler değil, düzgün isimli üç gerçek kütüphane hücresi: `o211a_2` (12 adet),
`conb_1` (6), `and4b_2` (4).

Dosyalar PDK'da vardı. Yani **geometri gerçekten farklıydı.** Hangi katmanda
farklı olduğuna baktım:

| Hücre | Farklı olan katmanlar |
|---|---|
| `o211a_2` | `poly`, `licon1` |
| `conb_1` | `npc` |
| `and4b_2` | `poly` |

Ve hepsinde `nwell`, `diff`, `li1`, `mcon`, implantlar, pin katmanları **aynen
tutuyordu**.

Bu şu demek: puzzle'ı çizen PDK sürümü, bizim indirdiğimizle tam aynı değil.
Fark küçük ve tipik bir DRC düzeltmesine benziyor — birkaç şekil rötuşlanmış.
Elektriksel yapı aynı.

Gerçek tersine mühendislikte bu **sürekli** başına gelir. Elindeki referans
kütüphane, incelediğin çipin üretildiği sürüm olmayabilir. Exact hash bunu
affetmez.

### Çözüm: iki katmanlı eşleştirme

**Katman 1, exact.** Bütün poligonların hash'i. En güçlü, kesin kimlik.

**Katman 2, structural.** Sadece `nwell`, `diff`, `li1`, `mcon` üzerinden hash,
artı pin isimleri kümesi, artı transistör sayısı.

Katman seçimi tesadüfi değil. `poly`'yi dışarıda bırakmak gate şekillerini
kaybettirir — ama `diff` ile `li1` birlikte **hangi transistörün seri hangisinin
paralel** bağlandığını hâlâ kodluyor, ki bir kapıyı dualinden ayıran tam olarak
bu. Ders 0'da gördüğümüz o "hiçbir yere bağlanmayan mor iç düğüm" hatırlıyor
musun? İşte o bilgi `li1`'de duruyor.

Ölçtüm: bu hash tek başına 437 hücrenin 427'sini benzersiz ayırıyor. Kalan 10
çift ise `lpflow_*` izolasyon hücreleri — bunlar zaten mantık eşdeğerleriyle
**birebir aynı layout**, sadece farklı amaçla adlandırılmışlar (`and2_1` ile
`lpflow_inputiso0n_1` gibi). Pin isimleri ve transistör sayısı eklenince hepsi
ayrışıyor, kütüphanede tek bir belirsiz parmak izi kalmıyor.

Bir kural daha koydum: **iki farklı hücreye denk gelen bir parmak izi
kullanılmaz, indeksten atılır.** İki hücreye uyan bir imza, kimlik tespiti
değildir. Rastgele birini seçmek, hatayı sessizleştirmek olur.

Sonuç: puzzle'da 1596 exact + 22 structural = 1618, ve structural olanların
hepsi de dosyadaki isimle uyuşuyor.

Buradaki asıl ders yöntemden çok tavırla ilgili: **eşleşmeyen her şeyi kaydet ve
bak.** Sessizce atsaydım, 22 mantık hücresi netlist'ten eksik çıkacaktı ve bunu
Faz 2'de anlamak neredeyse imkânsız olacaktı.

---

## 7. Bu dersin en önemli bulgusu

Digest her hücreyi ayırıyor. Peki gözle görebileceğin kaba özellikler — boyut ve
transistör sayısı — ayırıyor mu?

```
66 cells with transistors fall into 22 profiles
53 of them are NOT separated by profile alone
```

**Hücrelerin %80'i kaba profille ayırt edilemiyor.** Ve en çarpıcı örnek listenin
ilk satırı:

```
2.3x2.72, 8 transistör -> nand2_2, nor2_2, or2_2
```

Aynı boyut. Aynı transistör sayısı. Tamamen farklı mantık.

Bu tesadüf değil, yapısal bir gerçek. NAND ile NOR birbirinin **duali**:

```
        NAND2                          NOR2
         VDD                            VDD
      ┌───┴───┐                          │
     [A]     [B]   ← paralel            [A]   ← seri
      └───┬───┘                          │
          ├── Y                         [B]
         [A]        ← seri               │
          │                              ├── Y
         [B]                        ┌────┴────┐
          │                        [A]       [B]   ← paralel
         GND                        └────┬────┘
                                        GND
```

Aynı dört transistör. Sadece hangisinin seri hangisinin paralel bağlandığı
farklı. Ve seri/paralel **bağlantıdır**, geometrik bir sayım değil.

Ders 0'ın sonunda bunu zaten görmüştük: seri bağlantıyı, dışarı hiçbir yere
bağlanmayan o mor iç düğümden anlıyorduk. Yani ayrım orada, tellerde.

> **Boyut ve transistör sayısı sana hücrenin ne kadara mal olduğunu söyler,
> ne yaptığını söylemez. İşlev bağlantılarda yaşar.**

Bu, Faz 2'nin gerekçesi. Hücre seviyesindeki ölçümü ne kadar iyileştirirsen
iyileştir devreyi geri getiremezsin, çünkü o bilgi hücre seviyesinde **gerçekten
yok**.

---

## 8. Puzzle'da ne bulduk

```
placements  9875
identified  1618      ← 1596 exact + 22 structural
  logic     728       ← anlamamız gereken gerçek devre
  physical  890       ← dolgu, kuyu bağlantısı, decap, diyot
unmatched   8257      ← 8221 routing via + 36 marker (Morse satırı)
```

Sonuç `out/puzzle/instances.json` dosyasına yazılıyor. Bu dosya Stage 2'nin
girdisi — her aşama bir öncekinin çıktısını okuyor, GDS'e geri dönmüyor.

Yönelim dağılımı: 624 `N`, 546 `FS`, 233 `S`, 215 `FN`. Sıraların dönüşümlü
çevrildiğini burada da görüyorsun.

Sıralı elemanlar değişmedi: 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2` = **92 bit
durum**.

Küçük bir düzeltme: Ders 0'da mantık hücresi sayısını 722 demiştim. Doğrusu
728. Fark, 6 adet `conb_1`: sabit üreten hücreler. Onları önce fiziksel saymıştım
ama çıkışları gerçek netleri sürüyor, yani devrenin parçalar.

---

## 9. Kendin dene

```bash
# Bir kez: PDK hucre kutuphanesini indir (~4 MB, commit'e sabitli)
python tools/fetch_pdk.py

# Warm-up'i cevap anahtariyla dogrula, 230/230 gormelisin
python tools/stage1_cells.py warmup
python tools/compare_def.py warmup

# Puzzle: 1596 exact + 22 structural bekle
python tools/stage1_cells.py puzzle

# Hucre profilleri ve imza cakismalari
python tools/cell_signature.py puzzle/warmup/04_final.gds
```

Denemen için iki soru. Önce kendin düşün, cevaplar aşağıda.

1. `and2_2` 8 transistör çıkıyor, `nand2_2` de 8. Ama AND = NAND + inverter
   olması gerekmez miydi, yani daha fazla? Hücreleri çizdirip bak.
2. `clkbuf_16` 40 transistör ama sadece **2 poly şekli** var. Ders 0'daki
   "parmak" fikrini hatırla; 2 şekil nasıl 40 transistör yapar?

### Cevaplar

Her poly şeklinin kaç parmağı olduğunu ayrı ayrı saydırınca çıkıyor:

```
and2_2:     poly#1 -> 1 parmak     poly#2 -> 1 parmak     poly#3 -> 2 parmak
nand2_2:    poly#1 -> 2 parmak     poly#2 -> 2 parmak
clkbuf_16:  poly#1 -> 4 parmak     poly#2 -> 16 parmak
```

**Birinci soru.** `and2_2` gerçekten NAND + inverter. Üç poly şekli var: ikisi
NAND'ın A ve B girişleri, üçüncüsü çıkıştaki inverter. Ama parmak sayıları
farklı — NAND aşaması **tek parmaklı** (yani 4 transistör), inverter aşaması
**çift parmaklı** (4 transistör). Toplam 8.

Mantığı şu: hücrenin dışarıya söz verdiği sürme gücü sadece **son aşama** için
geçerli. İçerideki NAND yalnızca kendi inverter'ını sürüyor, o da hemen yanı
başında duran küçük bir yük. Onu güçlendirmek boşa alan ve boşa güç olurdu.
`nand2_2`'de ise tek aşama var, dolayısıyla o aşamanın kendisi güçlendirilmek
zorunda — bu yüzden iki girişi de çift parmaklı.

**İkinci soru.** `clkbuf_16` iki aşamalı bir tampon: iki inverter arka arkaya.
Birincisi 4 parmaklı, ikincisi 16 parmaklı. 4 × 2 diff = 8, 16 × 2 diff = 32,
toplam 40 transistör.

Buradaki 16 sayısı, hücrenin adındaki `_16`'nın ta kendisi. Ve 4 → 16 oranı
tesadüf değil: büyük bir yükü sürmek için transistörü tek hamlede devasa
yapamazsın, çünkü o zaman **onun** gate'i devasa bir yük olur ve sorunu bir
adım geriye taşımış olursun. Çözüm kademeli büyütmek — her aşama bir öncekinin
birkaç katı. Saat sinyalleri çipin en uzak köşelerine gitmek zorunda olduğu için
clock buffer'ları en agresif kademelenen hücrelerdir.

Yani hücrenin içindeki parmak sayılarına bakarak **kaç aşamalı olduğunu ve
nereye kadar sürmek üzere tasarlandığını** okuyabiliyorsun.

---

## Sonraki ders

Faz 2: **connectivity extraction**. Hangi pin hangi pine bağlı? Ders 0'daki
katman merdivenini (`licon1 → li1 → mcon → met1 → via → met2...`) bu sefer
tersten tırmanacağız. Bunu bulunca elimizde netlist olacak — yani devrenin
kendisi.
