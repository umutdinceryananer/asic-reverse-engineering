# Ders 3 — Devreyi etiketlemek

Ders 2'nin sonunda elimizde doğru bir netlist vardı. Ve tamamen okunamaz:

```verilog
sky130_fd_sc_hd__nor3_2  i06976 (.A(n00250), .B(n00272), .C(n00258), .Y(n00259));
sky130_fd_sc_hd__a31oi_2 i06991 (.A1(n00268), .A2(n00269), .A3(n00270), ...);
```

738 kutu, 723 tel. Hiçbir ismin anlamı yok. `n00258`'in ne olduğunu bilmiyoruz.

Bu ders o yığına **yapı** kazandırıyor. Dikkat: *anlam* değil, **yapı**. Aradaki
fark bu dersin yarısı.

Sonunda şunları biliyor olacaksın: kombinasyonel ile sıralı devrenin farkını,
bir flip-flop'un ne yaptığını, bir çipin neden "koni"lere ayrıldığını, ve
bilgiyi hangi kaynaktan almanın meşru olduğunu.

---

## 1. Devrelerin iki türü

Şimdiye kadar gördüğümüz her hücre — NAND, NOR, XOR, MUX — aynı şeyi yapıyordu:
**girişlere bak, çıkışı hesapla.** Girişler değişince çıkış da değişir. Hafızası
yoktur.

Bunlara **kombinasyonel** deniyor. Bir formül gibiler:

```
Y = (A NAND B)
```

Şimdi bir sorun. Sadece formüllerden oluşan bir devreyle şunu yapamazsın:

> "Bana bit bit gelen bir sayıyı biriktir, sonra toplamını söyle."

Neden yapamazsın? Çünkü biriktirmek için **hatırlaman** gerekir. Formül
hatırlamaz; girdi gidince çıktı da gider.

### Flip-flop: bir bit hatırlayan eleman

İşte bu yüzden ikinci bir eleman türü var. **Flip-flop** tek bir biti tutar.

Ders 1'de `dfrtp_2`'nin 30 transistör olduğunu görmüştük — bir NAND'in dört
katı. Ders 2'de sekiz iç düğümü olduğunu gördük. Şimdi neden bu kadar pahalı
olduğunu anlıyoruz: hatırlamak, hesaplamaktan zordur.

Flip-flop'un dört bacağı var:

| Bacak | İşi |
|---|---|
| `D` | girecek değer (data) |
| `Q` | şu an tutulan değer |
| `CLK` | **ne zaman** güncelleneceğini söyleyen sinyal |
| `RESET_B` | zorla sıfırla |

Kritik olan `CLK`. Flip-flop `D`'yi sürekli takip **etmez**. Sadece saat sinyali
yükseldiği anda `D`'ye bakar, gördüğünü içeri alır, ve bir sonraki saat kenarına
kadar onu `Q`'da tutar.

```
CLK   ▁▁▔▔▁▁▔▔▁▁▔▔▁▁       ← metronom
D     ▁▔▔▔▔▔▁▁▁▁▁▔▔▔       ← serbestçe değişebilir
Q     ▁▁▁▔▔▔▔▔▔▁▁▁▁▁       ← sadece CLK yükselirken değişir
        ↑     ↑     ↑
      yakala yakala yakala
```

### Saat neden var

İlk bakışta gereksiz bir kısıtlama gibi görünüyor. Değil — devreyi mümkün kılan
şey o.

Kombinasyonel mantık ışık hızında çalışmaz. Bir sinyalin NAND'den geçmesi zaman
alır, ve farklı yollar farklı sürer. Ortada bir düzenleyici olmasa, sonuçlar
birbirine karışırdı: bazı kapılar yeni değeri, bazıları hâlâ eskisini görürdü.

Saat şunu garanti ediyor: **bir kenardan diğerine kadar geçen sürede
kombinasyonel mantık işini bitirmiş olacak.** Sonra hep birlikte, aynı anda,
yeni değerler yakalanır. Herkes aynı adımda yürür.

### Ve buradan devrenin gerçek şekli çıkıyor

Bu iki eleman türünden şu resim doğuyor:

```
   ┌──────────────┐         ┌──────────────┐
   │ kombinasyonel│  ──D──▶ │  flip-flop   │ ──Q──┐
   │    mantık    │         │   (hafıza)   │      │
   └──────────────┘         └──────────────┘      │
          ▲                        ▲              │
          │                       CLK             │
          └───────────────────────────────────────┘
                        geri besleme
```

Her saat çevriminde: flip-flop'lar mevcut durumu tutar → kombinasyonel mantık
o durumdan yeni durumu hesaplar → saat kenarı gelir → yeni durum yakalanır →
tekrar.

> **Bir senkron devre, flip-flop'larla ayrılmış kombinasyonel adacıklardan
> oluşur.** Bu, çipin gerçek yapısıdır ve Stage 3'ün bulmaya çalıştığı şey de
> tam olarak budur.

---

## 2. Bu aşamanın işi nedir, ne değildir

Netlist'te 92 flip-flop ve 646 kombinasyonel hücre var. Ama netlist bunu
**söylemiyor.** Bize sadece kutular ve teller veriyor.

Stage 3 şunları etiketliyor:

- hangi tel saat
- hangi tel reset
- her flip-flop'un verisi nereden geliyor
- hangi teller sabit
- kombinasyonel adacıklar nerede başlayıp nerede bitiyor

Şunu **yapmıyor**: bu devrenin ne hesapladığını söylemek. O Stage 4 ve
sonrasının işi.

Ayrım önemli çünkü bu aşamada verilen her cevabın **tahminsiz** olması gerekiyor.
"Bu herhalde bir sayaçtır" cümlesi buraya girerse, sonraki bütün aşamalar o
tahminin üstüne kurulur.

---

## 3. Netlist'i okumak

Verilog ayrıştırmayı kendim yazabilirdim — dosyayı biz ürettik, biçimi basit.
Yosys'i seçtim, üç sebeple:

1. **Standart araç.** Bir tersine mühendislik pipeline'ının Verilog'u kendi
   yazdığı ayrıştırıcıyla okuması savunulabilir bir tercih değil.
2. **Bağımsız görüş.** Yosys'in `check` komutu netlist hakkında kendi fikrini
   söylüyor. Bizim ürettiğimiz dosyayı bir başkası doğruluyor.
3. **Sonraki aşamalar zaten ona muhtaç.** Stage 6'nın çözücüsü Yosys'in SMT2
   ihracını kullanacak.

Sonuç ikisinde de temiz:

```
warm up:  0 problems, 79 cells, 84 wires
puzzle:   0 problems, 738 cells, 716 wires
```

`hierarchy -check` ayrıca her instance'ın modülünü ve port uyumunu doğruluyor —
yani Stage 2'nin emitter'ına bedava bir çapraz kontrol.

### Yosys hücreleri nereden bilecek

Netlist'te `sky130_fd_sc_hd__nand2_2` yazıyor ama Yosys bunun ne olduğunu
bilmiyor. İki türlü anlatabilirim: hücrenin **ne yaptığını**, ya da sadece
**neye benzediğini**.

Şimdilik şekli yeterli — bu aşamanın sorusu "ne neye bağlı", "ne hesaplıyor"
değil. Bacakları ve yönleri yazan beş satırlık bir *blackbox* tanımı yetiyor.

**Ama bu seçimin bir sınırı var, ve o sınırı sonra öğrendim.** Stage 6'da
çözücüye devreyi vereceğiz, ve çözücünün her hücrenin ne hesapladığını bilmesi
gerekiyor. Blackbox'lardan SMT2 yazamazsın. Yani bu yol Stage 3'te yeterli,
Stage 6'da duvara çarpar.

Çözüm: hücre fonksiyonlarını yine de sakla, ileride lazım. Nereden geldikleri
bir sonraki bölümün konusu.

---

## 4. Bilgiyi kimden almalı: bu dersin asıl konusu

Şu soruyu cevaplamam gerekiyordu: **92 flip-flop'un her birinde hangi bacak
saat, hangisi reset, hangisi veri?**

Elimde üç aday kaynak vardı.

### Aday 1: isimler

Pin `CLK` diyorsa saattir. Hücre `dfrtp` ise reset'i vardır.

Kulağa mantıklı geliyor ve **çoğunlukla** doğru. Ders 1'in tamamı isimden
tanımayı bırakıp geometriye geçmekle geçmişti; Ders 2'de `USE SIGNAL` filtresi
bütün saatleri sessizce silmişti. Bu projede isme güvenmenin bir geçmişi var.

### Aday 2: LEF'in `USE CLOCK` işareti

LEF, pinlerin fiziksel tanımı. İçinde `USE CLOCK` diye bir işaret var, ve
kütüphanedeki 69 hücrede bulunuyor.

### Aday 3: liberty

Ve üçüncü bir dosya türü daha var, ki ben başta **bakmamıştım**.

Liberty, bir hücrenin ne yaptığını yazan dosya. İçeriği şöyle:

```
dfrtp_2:  clocked_on=CLK   next_state=D   clear=!RESET_B
dfstp_2:  clocked_on=CLK   next_state=D   preset=!SET_B
nand2_2:  Y function=(!A) | (!B)
conb_1:   HI function=1    LO function=0
```

Türetmeye çalıştığım her şey burada, **işlevsel olarak yazılı.** Saat tahmin
değil `clocked_on`. Reset isim eşleştirmesi değil `clear`, üstelik polaritesiyle
(`!` işareti "düşük seviyede aktif" demek).

### Ben ilk iki adayı seçmiştim

Kararımı şöyle savunmuştum: saat LEF'ten gelir, çünkü orada **beyan edilmiş**;
reset/set için de pin adı ile hücre adının **anlaşmasını** şart koşarım, böylece
iki bağımsız kaynağım olur.

Kulağa sağlam geliyor. İkisi de yanlıştı.

**"İki bağımsız kaynak" yanlıştı.** Pin adı ile hücre adı bağımsız değil — ikisi
de *aynı isimlendirme kuralının* iki ifadesi, aynı kişiler aynı anda yazmış.
Kural yanlış uygulanmışsa ikisi birden yanlış olur. Bu, aynı cümleyi iki kez
okumak.

Ve kural zaten yetmiyor: kütüphanede **hem `RESET_B` hem `SET_B` taşıyan altı
hücre** var (`dfbbp_1` ve kardeşleri; adındaki `bb` = "both"). Orada isimden
çıkarım komple çöküyor.

**LEF eleştirim de yanlıştı** — ama ters yönden. `USE CLOCK`'un güvenilmez
olduğunu iddia ettim ve kanıt olarak tek bir hücre gösterdim:
`lpflow_inputisolatch_1`, `SLEEP_B` pinini saat işaretliyor, ve `SLEEP_B` bir
güç-kesme kontrolü.

Ölçtüm. Liberty de o hücreye `clocked_on = SLEEP_B` diyor. Çünkü o eleman bir
**latch**, ve bir latch'in enable'ı liberty terimleriyle gerçekten onun saatidir.
Karşı örnek değilmiş. Bütün kütüphanede karşılaştırdım: **429 hücrenin 429'unda
LEF ile liberty aynı fikirde.**

Yani `USE CLOCK` sorunsuzdu, ben onu tek bir hücreye bakıp, ölçmeden
suçlamıştım.

### Bu dersin metodoloji cümlesi

İki hata da aynı şeyden çıkıyor:

> **Bir kaynağa, hak etmediği yetkiyi vermek.**

İsme "karar verici" yetkisi verdim, oysa o bir konvansiyon. LEF'e "güvenilmez"
damgası vurdum, oysa ölçmemiştim. Ve gerçek yetki sahibi olan liberty'ye hiç
bakmamıştım — üstelik sabitlediğimiz commit'te, indirilmeyi bekliyordu.

Şimdiki düzen:

| Kaynak | Rolü |
|---|---|
| **liberty** | **karar verir** — `clocked_on`, `next_state`, `clear`, `preset` |
| LEF | çapraz kontrol, uyuşmazlığı raporlar |
| isim | çapraz kontrol, uyuşmazlığı raporlar |

İkisi de her iki hedefte liberty ile uyuşuyor. Uyuşmasalardı program bunu
yazardı; sessizce birini seçmezdi.

> Bir olguyu iki kaynaktan almak değerlidir. **Ama kaynakların gerçekten farklı
> şeyler gözlemliyor olması gerekir.** Aynı belgeyi iki kez okumak doğrulama
> değildir.

---

## 5. `bool("false")` — kullanılmadan yakalanan hata

Liberty okuyucusunu yazdım. İlk çalıştırmada `a2111o_1` hücresinin `A1`, `A2`,
`B1`, `C1`, `D1` girişlerinin **hepsini saat** işaretledi. Kombinasyonel bir
hücrenin bütün girişleri.

Sebep, dosyanın kendisinde:

```json
"clock": "false"
```

Bu bir metin, boolean değil. Ve Python'da:

```python
bool("false")   # True  ← boş olmayan bir string
```

Kütüphanedeki her kombinasyonel hücrenin her girişi saat olmuş oluyor.

Bu **sessiz** bir hata: netlist geçerli kalır, simülasyon geçer, sadece saat
etiketleri saçma olur. Ve saat etiketleri Stage 4'ün desen aramasının temeli.

Nasıl yakalandı: okuyucuyu kullanmadan önce, LEF'in kendi saat işaretiyle
**bütün kütüphane üzerinde** karşılaştırdım. 429 hücrenin 414'ünde uyuşmazlık
raporladı — gerçek olamayacak kadar büyük bir sayı. Düzeltince sıfır.

> Ders 2'de "iki bağımsız yol aynı sonuca çıkıyorsa sonuç doğrudur" demiştik.
> Tersi de geçerli ve daha kullanışlı: **çıkmıyorsa bir tanesi bozuktur, ve
> hangisi olduğunu bulmaya değer.**

---

## 6. Ne türetiliyor

### Saat ağacı

Saat, çipin en uzak köşelerine gitmek zorunda. Tek bir flip-flop'un saat girişi
küçük bir yük, ama 92 tanesi değil. O yüzden saat **dallandırılır**: tamponlar
yükü paylaşır.

Warm-up'ta:

```
n00076: clkbuf_16 sürüyor, 8 flip-flop'a gidiyor
n00032: clkbuf_16 sürüyor, 8 flip-flop'a gidiyor
```

İki dal, sekizer flop, toplam 16. Ders 1'de `clkbuf_16`'nın neden 40 transistör
ve iki kademe olduğunu konuşmuştuk — sürdüğü yük işte burada, sayıyla.

### Reset ve set

`clear` ve `preset` niteliklerinden, aktif seviyesiyle birlikte.

### Veri kaynağı ve enable

Her flip-flop için `D`'yi kimin sürdüğü. Ama burada güzel bir ayrıntı var.

Bu kütüphanedeki **hiçbir flip-flop'ta "enable" bacağı yok.** Peki bir devre
"bu çevrimde değeri güncelleme, koru" demeyi nasıl başarır?

D'nin önüne bir mux koyarak. Mux'ın bir bacağı yeni veri, öbür bacağı
flip-flop'un **kendi çıkışı**:

```
      yeni veri ──▶│A1  │
                   │mux │──▶ D ──▶│flip-flop│──▶ Q ──┬──▶ devrenin geri kalanı
      Q ──────────▶│A0  │         └─────────┘        │
                   └─▲──┘                            │
                     │                               │
                    en (seçim)                       │
                     └───────────────────────────────┘
```

`en` bir yöne bakınca yeni veri girer, öbür yöne bakınca flip-flop kendi
değerini geri okur — yani **değişmez.** Enable budur.

Bu yapısal bir olgu, yorum değil, o yüzden Stage 3'e ait. Warm-up'ta gerçek
kayıt:

```
i00210 mux2_1: A0=n00018  A1=n00004  S=en  X=n00080
i00141 dfrtp_2: D=n00080 ... ve Q'su n00018
```

Mux'ın `A0` bacağı, flip-flop'un kendi `Q`'su. `en` düşükken tutuyor.
**Warm-up'taki 16 flip-flop'un 16'sında da bu desen var, hepsinde `en` neti.**

### Sabitler

Bazı teller hiç değişmez, sürekli 1 veya 0'dır. Bunları üreten hücre `conb_1`.

Ama hücrenin *adına* bakarak bulmuyorum — liberty'nin fonksiyonuna bakıyorum:

```
conb_1:  HI function=1    LO function=0
```

Böylece başka adlı bir sabit üreteci de yakalanır.

---

## 7. Koniler: kombinasyonel adacıkları bulmak

Bölüm 1'deki resmi hatırla: devre, flip-flop'larla ayrılmış kombinasyonel
adacıklardan oluşuyor. Şimdi o adacıkları bulacağız.

### Tanım

Bir **koni** (cone), tek bir sonuca akan kombinasyonel mantığın tamamıdır.

Nereden başlarsın? Kombinasyonel mantığın **bittiği** yerlerden. Üç tane var:

- bir flip-flop'un `D` girişi
- bir flip-flop'un reset/set girişi
- çipin bir çıkış portu

Bunlara **kök** diyoruz. Kökten geriye doğru yürürsün. Nerede durursun? Üç
yerde:

- bir flip-flop'un `Q` çıkışına vardığında (orası geçen çevrimin sonucu)
- bir giriş portuna vardığında
- bir sabite vardığında

Yürürken geçtiğin her tel o koninin üyesidir.

### Neden değerli

Çünkü bir koni şu soruyu cevaplıyor: **bu sonuç, bu çevrimde neye bağlı?**

Ve konilerin **boyutları** devrenin şeklini ele veriyor. Warm-up'ta ölçtüm:

```
33 kök
en küçük koni:   1 net
en büyük koni:  60 net
en büyük beşli: port.S=60, sonra dört tane 4'lük
```

Bu tablo tek başına çok şey söylüyor. **Bir tane devasa koni var** (`S` çıkış
portu, 60 net) ve geri kalanların hepsi minik (4 net).

Neden? Çünkü warm-up bir kaydırmalı yazmaç artı bir toplayıcı. Her flip-flop'un
`D`'si bir mux'tan bir önceki flop'a bağlanıyor — kısa yol, küçük koni. Ama `S`
çıkışı bütün toplama mantığından besleniyor — uzun yol, büyük koni.

`S`'nin konisine bakınca ne hesapladığı da beliriyor:

```
xor2_2, xor2_2, xor2_2, xnor2_2, xnor2_2, and2_2, nor2_2, a31o_2, ...
ve 16 tane dfrtp_2 çıkışı
```

Bir sürü XOR ve XNOR. Ders 1'de "işlev bağlantılarda yaşar" demiştik — işte
bağlantılardan işlev sızmaya başlıyor. Bir toplayıcının imzası bol XOR'dur.

**Ama Stage 3 bunu söylemiyor.** Sadece koniyi çıkarıyor. "Bu bir toplayıcı"
demek Stage 4'ün işi, ve orada bir *algoritma* söyleyecek, sezgi değil.

---

## 8. Sonuçlar

| | warm-up | puzzle |
|---|---|---|
| Hücre | 79 | 738 |
| Net | 84 | 723 |
| Saat neti | 2 | 16 |
| Saat sürücüsü | `clkbuf_16` x2 | `clkbuf_8` x16 |
| Dal başına flop | 8, 8 | on iki dalda 6, dört dalda 5 |
| Durum elemanı | 16 `dfrtp_2` | 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2` |
| Mux'lu enable | 16, hepsi `en` | 12, hepsi tek net |
| Reset neti | 1 (`rst_n`, 16 pin) | 1 (`rst_n`, 88 pin) |
| Set neti | 0 | 1 (`rst_n`, 88 pin) |
| Sabit net | 0 | 12 (altı 1, altı 0) |
| Koni kökü | 33 | 189 |

İki satırı iki kez okumaya değer.

### Saat ağacı tam kapanıyor

12 dal × 6 flop + 4 dal × 5 flop = **92**. Tam olarak flip-flop sayısı.

Bu küçük bir aritmetik gibi görünüyor ama güçlü bir kanıt: **saatsiz kalan
eleman yok, iki kez saatlenen yok.** Ve bunu doğrulamak için cevap anahtarı
gerekmedi — sayılar kendi içinde kapandı.

### `rst_n` hem reset hem set

Puzzle'da aynı tel, 84 flip-flop'u **temizliyor** ve 4 tanesini **kuruyor**.

Yani reset'ten çıkan devre sıfırlarla dolu değil; dört bit 1 olarak başlıyor.

Bunu daha önce de biliyorduk — Ders 1'de Stage 1, `dfstp_2` hücrelerini
**geometriden** saymıştı, 4 tane. Şimdi Stage 3 aynı sayıya liberty'nin `preset`
niteliğinden, tamamen ilgisiz bir yoldan ulaştı.

**İki bağımsız yol, aynı sayı.** Bu projede en çok işe yarayan alışkanlık.

---

## 9. Kapı: round-trip

Bu aşamanın doğru çalıştığını nasıl gösteririz?

Spec'in cevabı zarif: **graf'ı tekrar Verilog'a çevir, ve Stage 2'nin
simülasyonundan geçir.** Graf devreyi kaybetmişse, geri yazılan Verilog aynı
sonucu vermez.

Bir tuzak var ve ona düşmemek önemliydi: geri yazarken **Stage 2'nin dosyasına
bakmak yasak.** Bakarsak test "kopya kopyaya eşit mi" sorusunu cevaplamış olur,
ki her zaman evettir. Verilog **yalnızca graf'tan** yazılıyor.

```
warm up: 65536 operand çifti, 15 başarı, 0 uyuşmazlık   PASS
puzzle:  312 çevrim, 0 uyuşmazlık                       PASS
```

İkisi de geçiyor.

---

## 10. Kendin dene

```bash
# eda imaji gerekli (Yosys + z3)
DOCKER_BUILDKIT=0 docker build --target eda -t gds-teardown-eda -f docker/Dockerfile docker/

python tools/stage3_graph.py warmup
python tools/sim/run.py warmup --netlist out/warmup/graph.v   # round-trip kapisi

python tools/stage3_graph.py puzzle
python tools/sim/run.py puzzle --netlist out/puzzle/graph.v
```

Üç soru.

1. Warm-up'ta koni boyutları `60, 4, 4, 4, ...` şeklinde. Puzzle'da en büyük
   koni üyeliği 88. Bu 88 sayısı nereden geliyor, ve bir koninin *büyük* olması
   ne anlatır?
2. Bölüm 6'daki enable deseni: mux'ın bir bacağı flop'un kendi `Q`'su.
   Peki bir devre bu deseni **kullanmadan** da "değeri koru" diyebilir mi?
3. Stage 3 hücreleri blackbox olarak Yosys'e verdi ve bunun Stage 6'da
   yetmeyeceğini söyledik. Peki neden Stage 3'te yetiyor?

### Cevaplar

**1.** 88, `rst_n` netinin dokunduğu pin sayısı: 84 `RESET_B` + 4 `SET_B`. Yani
`rst_n` 88 farklı koni köküne besleme yapıyor, ve o yüzden 88 koninin üyesi.

Bir koninin büyük olması, o sonucun **çok şeye bağlı** olması demek. `rst_n`
için bu beklenen: reset her yere gider. Ama bir *veri* konisi büyükse, o
flip-flop'un girişi çok sayıda başka bitten hesaplanıyor demektir — toplayıcı,
karşılaştırıcı, ya da geniş bir mantık bloğu. Küçük koni ise basit bir aktarım:
kaydırmalı yazmaçta her bit sadece bir öncekine bakar.

Yani koni boyutu dağılımı, devrenin **kaba haritası**. Stage 4 aramaya buradan
başlayacak.

**2.** Evet, en az iki yolu daha var.

Biri: **saati kesmek** (clock gating). Flip-flop'a saat kenarı hiç gelmezse
değeri zaten korur. Alan ve güç açısından daha ucuz, ama saat ağacına dokunmak
zamanlama açısından risklidir, o yüzden sentez araçları genellikle bunu
kendiliğinden yapmaz.

Diğeri: kütüphanede **enable bacağı olan** flip-flop kullanmak. sky130'da yedi
tane var: `edfxtp_1`, `edfxbp_1`, ve beş tane tarama (scan) varyantı.

Ve şuna bak — `edfxtp_1`'in liberty tanımı:

```
pinler:      CLK, D, DE, Q
next_state:  (D & DE) | (IQ & !DE)
```

`IQ` flip-flop'un kendi tuttuğu değer. Yani formül şunu diyor: *"DE yüksekse D'yi
al, değilse kendi değerini koru."*

**Bu, bölüm 6'daki mux deseninin formül olarak yazılmış hali.** Aynı devre, biri
iki hücreyle kurulmuş, diğeri tek hücrenin içine gömülmüş. Tasarımcı hangisini
seçerse seçsin işlev aynı; fark alan, güç ve sentez aracının tercihinde.

Bu tasarım gömülü olanı kullanmamış — ki bu da bir bilgi: tasarımcının hangi
hücre kümesiyle çalıştığını söylüyor.

Bir de kodun buradaki davranışı önemli. `edfxtp_1`'in `next_state`'i tek bir pin
değil, bir **ifade**. Stage 3'ün rol çıkarımı tek pine indirgeyemediği bir
sıralı hücreyle karşılaşınca **duruyor**, tahmin etmiyor:

> `... is sequential but its liberty entry does not reduce to one clock, one
> data pin and one output; add a rule rather than guessing`

Yani bu varsayımsal bir koruma değil; onu tetikleyecek hücrenin adını
söyleyebiliyorum. Bir gün o hücre bir hedefte çıkarsa, sessiz bir yanlış cevap
değil, gürültülü bir duruş alacağız.

**3.** Çünkü iki aşama farklı sorular soruyor.

Stage 3'ün sorusu **topolojik**: hangi tel nereye gidiyor, sınırlar nerede.
Bunun için kutunun bacaklarını bilmek yeter, içini bilmek gerekmez.

Stage 6'nın sorusu **anlamsal**: "success'i 1 yapan bir girdi dizisi var mı?"
Bunu cevaplamak için çözücünün her kutunun içindeki denklemi bilmesi gerekir.
`Y = (!A) | (!B)` olmadan çözücüye verecek bir şey yok.

Bu yüzden liberty'nin `function` ifadeleri `graph.json`'a yazılıyor: Stage 3
kullanmıyor, Stage 4 ve 6 kullanacak. **Bir aşamanın ihtiyacı olmayan bir bilgiyi
taşıması, sonraki aşamanın onu yeniden keşfetmesinden ucuzdur.**

---

## Sonraki ders

Elimizde artık etiketli bir graf var: saatler, resetler, koniler, sabitler.

Sıradaki soru şu: **bu 738 kutu hangi bloklara ayrılıyor, ve o bloklar ne
yapıyor?** Sayaç mı, kaydırmalı yazmaç mı, toplayıcı mı, karşılaştırıcı mı?

Ama önce bir sorun çözmemiz gerekiyor. Bir detektör yazacağız — "bu bir
sayaçtır" diyen bir algoritma. Peki **doğru çalıştığını nereden bileceğiz?**
Puzzle'ın cevap anahtarı yok.

Cevap: cevabını bildiğimiz devreleri **kendimiz üreteceğiz**. Sayaçlar,
kaydırmalı yazmaçlar, toplayıcılar, LFSR'lar — bir sentetik korpus. Detektör
önce onlarda çalışmalı.

Bu yüzden bir sonraki ders Stage 4 değil, **Stage 5**: test setini,
detektörlerden önce kurmak.
