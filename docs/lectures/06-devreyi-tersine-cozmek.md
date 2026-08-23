# Ders 6 — Devreye ne yazmalı: tersine çözmek

Şimdiye kadar sorduğumuz her soru aynı türdendi: **bu ne?** Bu dikdörtgen hangi
katman, bu hücre hangi kapı, bu tel nereye gidiyor, bu 92 flop hangi
yazmaçlara ayrılıyor.

Bu dersin sorusu tür değiştiriyor:

> **Bu devreye ne yazmalıyım ki `success` çıkışı 1 olsun?**

Artık devreyi tarif etmiyoruz, **ters çeviriyoruz.** Elimizde bir fonksiyon
var ve çıktısı verilmiş; girdiyi arıyoruz.

Ders bittiğinde şunları biliyor olacaksın: bir çözücünün (solver) ne yapıp ne
yapmadığını, sıralı bir devrenin neden tek bir SAT sorusuna sığmadığını,
"başlangıç durumu serbest" hatasının neden bütün cevapları çöpe attığını, ve
kendinden emin, kendi içinde tutarlı, **yanlış** bir çözücü cevabının nasıl
yakalandığını.

---

## 1. Çözücü nedir

Bir SAT çözücü (satisfiability solver) tek bir soruyu cevaplar:

> Şu boolean denklem sistemini **doğru** yapan bir değişken ataması var mı?

Girdi: `(A veya B) ve (A değil veya C) ve ...`. Çıktı ya "işte bir atama:
A=1, B=0, C=1", ya da "hiçbir atama yok, kanıtı bu".

Sihir değil — devasa ama sistematik bir arama, on yıllardır biriken kısayollarla.
Bizim için önemli olan tek şey şu: **devreyi denkleme çevirebilirsek, çözücü
girdiyi bulur.**

Ve devreyi denkleme çevirmek zor değil, çünkü Ders 3'ten beri her hücrenin ne
hesapladığı elimizde. `graph.json` her hücrenin liberty fonksiyonunu taşıyor:

```
nand2_2:  Y = (!A) | (!B)
```

Bu zaten bir denklem. 738 hücre, 738 denklem. Teller değişken. Çözücüye
"success = 1" kısıtını ekle, sor.

### Ama tek soru yetmiyor

Yukarıdaki resim **kombinasyonel** bir devre için doğru. Bizimki değil.

Ders 3'ün resmini hatırla: devre, flip-floplarla ayrılmış kombinasyonel
adacıklardan oluşuyor. Flip-flop'un çıkışı bu çevrimde ne olduğuna değil,
**geçen çevrimde ne yakaladığına** bağlı. Ve puzzle'ın girişi `I` **tek bit** —
yani bilgi devreye bir çevrimde bir bit giriyor.

Dahası, Ders 4'te ölçtüğümüz bir olgu var: `success` yazmaçlanmış bir çıkış ve
onu süren flopun veri konisi **yalnızca R0'ın 57 bitine** bağlı. Ne birincil
giriş var orada, ne sabit. Yani:

> Success koşulu, **saklanan durumun** fonksiyonu. Girdiler ona ancak
> çevrimler boyunca durumu değiştirerek ulaşabilir.

Tek bir denklem sistemi bunu ifade edemez. Zamana ihtiyacımız var.

---

## 2. Açma (unrolling): zamanı denklemle yazmak

Çözüm zarif. Zamanı modelleyemiyorsan, **kopyala.**

Devrenin durumunu `S(0)` diye adlandır. Bir çevrim sonrası `S(1)`, sonra
`S(2)`... Her çevrim için devrenin kombinasyonel mantığının **ayrı bir
kopyasını** yaz:

```
girdi(0) ─┐
          ├─► [devrenin kopyası] ─► S(1) ─┐
S(0) ─────┘                               │
                                          │
girdi(1) ─┐                               │
          ├─► [devrenin kopyası] ─────────┴─► S(2) ─┐
                                                     │
girdi(2) ─┐                                          │
          ├─► [devrenin kopyası] ──────────────────┴─► S(3) ...
```

K çevrim için K kopya. Sonra kısıtı ekle: **`success`, K. çevrimde 1 olsun.**
Çözücüye ver. Dönerse cevap, her çevrimdeki girdi değerlerinin listesidir —
yani devreye ne yazacağın.

Buna **sınırlı model denetimi** (bounded model checking, BMC) deniyor.
"Sınırlı", çünkü K'yı sen seçiyorsun: "en fazla K çevrimde success'i yükselten
bir dizi var mı?" Yoksa K'yı büyütüp tekrar sorarsın.

### Negatif cevabın tuzağı

Burada spec'in özellikle uyardığı bir hata var. Çözücü "yok" derse, bu **iki**
farklı şey anlamına gelebilir:

1. Böyle bir girdi dizisi gerçekten yok.
2. Var ama K'dan uzun.

İkisi de aynı çıktıyı verir. O yüzden bu projede **her negatif cevap ulaşılan
derinliği taşımak zorunda:**

```
no input sequence drives S high within 7 cycles
DEPTH REACHED: 6. A negative without its depth is not a result.
```

Ne kadar ciddiye alındığını gösteren bir ölçüm var: `scale_datapath`
devresinin `done` çıkışı, serbest çalışan bir sayaç dolduktan sonra yükseliyor
— w16'da 256 çevrim, w64'te 2^56. Yani **hiçbir makul derinlikte bulunamaz.**
Araç bunu 32. derinlikte, derinliğini söyleyerek raporluyor. Ulaşılamayan bir
özellik ile bir çevrim eksik kalmış bir özellik, ancak derinlik yazılıysa
ayırt edilebilir.

---

## 3. Önce şunu sor: doğru devreyi mi çözüyorum?

Stage 6, `graph.json`'ı ters çeviriyor. `graph.json` yanlışsa, çözücü yanlış
devreyi çözer ve bunu **kendinden emin** biçimde yapar. Çözücü sana asla
"emin değilim" demez.

Arkada üç kontrol zaten duruyordu: DEF yerleşim için, simülasyon davranış
için, ikinci bir çıkarıcı bağlantı için. Hiçbiri burada gerekeni söylemiyor.
Fark tek cümlede:

```
simülasyon der ki:  bu ikisi, benim koştuğum vektörlerde aynı davrandı
kanıt (miter) der ki: bu ikisi, HER girdi dizisinde aynı davranır, işte kanıtı
```

**Miter** şu demek: iki devreyi yan yana koy, aynı girdileri ver, çıkışlarını
karşılaştır, ve çözücüye sor — "bunlar hiç farklı davranabilir mi?" Cevap
"hayır, imkânsız" ise, iki devre **denktir** ve bu bir kanıttır.

Peki neye karşı kanıtlayacağız? Ve burada bu projenin en utanç verici
bulgusuna geliyoruz.

### Beş aşama boyunca okunmayan cevap anahtarı

`puzzle/warmup/01_netlist.v` — warm-up'ın gerçekten üretildiği kapı seviyesi
netlist — ilk commit'ten beri repoda duruyordu. **Hiçbir araç açmamıştı.** Beş
aşama boyunca, onun yerine sentetik bir korpus kuruldu (Ders 5), ve o korpusun
en büyük zaafı "cevap anahtarını da biz yazdık" idi. Oysa yazmadığımız bir
cevap anahtarı, elimizin altında bekliyordu.

`docs/problems.md` 34 bu. Ve `verify_equiv.py` onu ilk kez açan araç:

```
$ python tools/verify_equiv.py warmup
  ports agree: A, B, S, clk, en, rst_n
yosys: 153 correspondence points
  every one proven, including the design's output
RESULT: pass
```

Kurtarılan netlist ile referans netlist **sıralı olarak denk** — 153 karşılık
noktasının hepsi kanıtlanmış. İkisi de 225 hücreye indirgeniyor, aynı
dağılımla. Bu kendi başına küçük bir bulgu: yerleşim ve yönlendirme mantığı
değiştirmemiş, ve Stage 1–3 onu **birebir** kurtarmış.

### İki ayar, ikisi de yanılarak bulundu

Bu kanıt kolay gelmedi ve iki ayar olmadan hiçbir şey kanıtlamıyordu:

- **`async2sync`.** Floplar asenkron reset taşıyor, SAT motorunun `$adff` için
  modeli yok. Bu olmadan her adım uyarı verip düşüyor — netlist'lerle hiç
  ilgisi olmayan bir sebeple.
- **`prep` yerine `proc; flatten; opt_clean`.** `prep` optimize eder; bağımsız
  optimize edilmiş iki tasarım yapısal olarak karşılaştırılamaz hale gelir.
  `equiv_struct` hiçbir eşleşme öneremez, ve sonuç **153'ün 0'ı kanıtlandı**
  olur. İki türlü de ölçüldü.

Sıfır kanıt da "hata" vermiyordu — sadece sessizce hiçbir şey kanıtlamıyordu.
Ders 5'in `clkbufmap` hikâyesinin aynısı: **sessizce hiçbir şey yapmak, bu
projede en sık rastlanan başarısızlık türü.**

### Ve bilinen-kötü girdi

Kanıtın kendisi yanılabiliyor mu? `graph.v`'nin bir kopyasında tek bir
`nand2_2` hücresi `nor2_2` yapıldı — aynı bacaklar, farklı fonksiyon:

```
126 could not be proven
RESULT: fail                                          [exit 1]
```

### Miter neyi kanıtlamıyor

Dürüstlük notu, ve önemli: iki netlist de **aynı** `celllib.py` üzerinden
okunuyor — yani hücrelerin ne hesapladığı konusunda ikisi de bu reponun
liberty okumasına dayanıyor. Bu okuma yanlışsa, hata **iki tarafta da aynı
şekilde** görünür ve sadeleşir.

Yani miter şunu kanıtlıyor: aynı durum, aynı bağlantı, aynı fonksiyonlar. Şunu
kanıtlamıyor: bu fonksiyonlar silikonu doğru tarif ediyor. O yarı başka yerde,
iki kez kapatılıyor — `verify_functions.py` (PDK'nın kendi davranışsal
modellerine karşı 850 tam doğruluk tablosu, Ders 4) ve birazdan göreceğimiz
replay kapısı.

---

## 4. Çevrim modeli, ve reddettiği iki tasarım

Denklemleri yazmadan önce "bir çevrim ne demek" sorusunu tam olarak
cevaplamak gerekiyor:

```
S(t)      t çevriminde flopların durduğu durum (asenkron reset/set uygulanmış)
r(t)      reset aktif mi — her flopun reset pinindeki netten okunur
comb(t)   bütün kombinasyonel netler, t'deki girdilerden ve S(t)'den
S(t+1)    r(t) VEYA r(t+1) ise reset değeri, değilse D(t)
```

Son satırdaki `r(t) veya r(t+1)`, asenkron reseti asenkron yapan şeydir: kenar
boyunca tutulan bir seviye, flopu **kenarın iki yanından da** temizler. Senkron
olsaydı sadece `r(t)` bakardık.

**Bir çevrim bir saat kenarıdır, yani saat bir sinyal değildir.** Saat ağacı
hücreleri modelden atılıyor, saat portu örtük. Bu aşamanın tek gerçek defekti
tam buradaydı: `graph.json`'ın `clock_nets` alanı **flop pinlerindeki**
netleri sayıyor, ağacın tamamını değil. Warm-up'ın ağacı `clk → n8 → {n18,
n41}` ve n8 o listede yok. İlk sürüm n8'i sıradan mantık sanıp modelledi —
sonuç: **saat, çözücünün seçmesi gereken bir değişken oldu.** Artık ağaç
floplardan geriye yürünüyor (`docs/problems.md` 39).

### Modelin tarif edemediği iki tasarım — ve söylediği

Bir model, tarif edemediği bir şeye rastladığında iki şey yapabilir: yaklaşık
bir cevap üretir, ya da durur. Bu araç duruyor:

- **Bir flopun clock pini dışında okunan saat neti** (kapılanmış veya
  örneklenmiş saat) — bir çevrimin kenar olduğu modelde bunun karşılığı yok.
- **Bir floptan hesaplanan reset** — `r(t) veya r(t+1)` tanımı kendine atıf
  yapar.
- Ve `--post-reset` için: **hem asenkron set hem asenkron clear taşıyan bir
  flop.** (Sebebi ilginç: model "ikisi de aktif" durumunu iki farklı yerde iki
  farklı şekilde cevaplıyor — 0. çevrimde çözümsüz, sonraki çevrimlerde set
  baskın. İkisi de tek başına yanlış değil, ama birbirleriyle çelişiyorlar, o
  yüzden tasarım çözülmüyor **reddediliyor**.)

Üçü de çözmeden önce kontrol ediliyor ve exit 2 ile duruyor. Hiçbiri warm-up'ta
ya da puzzle'da yok — ama kontrol, "yok" cümlesini bir okumadan **ölçülmüş bir
olguya** çeviriyor.

---

## 5. Serbest başlangıç durumu: bütün cevapları çöpe atan hata

Şimdi bu dersin en öğretici bölümü.

Devreyi K çevrim açtık. Peki `S(0)` — çevrim 0'daki durum — ne?

En kolay cevap: **serbest bırak.** Çözücü ne isterse seçsin. Bu, sorunun
çözücüye en kolay geldiği hâl.

Ve tamamen yanlış cevaplar üretiyor.

Ölçüm: warm-up'ta **0'dan 7'ye kadar her derinlikte** çözücü bir trace
buluyor. Her biri sorulan sorunun gerçek bir çözümü. Ve her biri işe yaramaz —
çünkü her biri, flopların **çözücünün seçtiği** bir durumda başlamasına bağlı.

> Hiçbir çip, birinin seçtiği bir durumda açılmaz.

Yani çözücü şunu diyordu: "success'i 1 yapabilirim — yeter ki devre şu 16
bitlik durumda açılmış olsun." Kullanışsız bir cevap, ama sorulan soruya
kusursuz uyuyor. **Hata çözücüde değil, soruda.**

### Karşı-örnek güdümlü döngü

Çözüm zarif ve bir kez öğrenince her yerde işe yarıyor. Her aday cevabı **ters
soruya** tabi tut:

> Bu girdi dizisinin **başarısız olduğu** bir başlangıç durumu var mı?

Varsa, çözücü onu bulur. O durumu al, tasarımın **ikinci bir kopyası** olarak
sabitle — girdi değişkenlerini paylaşan ama o durumdan başlayan bir kopya — ve
tekrar çöz. Şimdi çözücünün bulacağı cevap her iki durumdan da çalışmak
zorunda. Yine bir karşı-örnek çıkarsa, üçüncü kopya. Döngü, hiçbir karşı-örnek
kalmayınca biter.

Sonuç: **her açılış durumundan çalışan** bir girdi dizisi.

```
depth   7  1 start state       trace found
        bir başlangıç durumu onu yeniyor; sabitleyip tekrar (tur 1)
depth   7  2 start states      no trace          ← 7 gerçekten yetmiyormuş
depth   8  1 start state       trace found
        bir başlangıç durumu onu yeniyor; sabitleyip tekrar (tur 1)
depth   8  2 start states      trace found
        hiçbir başlangıç durumu yenemiyor: her durumdan geçerli
```

Derinlik 8 hayatta kalan ilki. Ve dikkat: **trace hiç reset kullanmıyor** —
`rst_n` dokuz çevrimin dokuzunda da yüksek. İhtiyacı yok, çünkü sekiz kaydırma
iki yazmacın üzerine tamamen yazıyor. İçine reset preamble'ı gömülmüş bir araç
buna bir çevrim harcayıp "derinlik 9" derdi.

---

## 6. Cevap, ve kimsenin ona söylemediği şey

```
  cycle       A       B      en   rst_n
      0       1       1       1       1
      1       1       1       1       1
      2       1       1       1       1
      3       1       1       1       1
      4       1       0       1       1
      5       1       1       1       1
      6       0       0       1       1
      7       0       0       1       1
      8       0       0       0       1   ← S = 1
```

En anlamlı bit önce okunursa: `A = 11111100` = **252**, `B = 11110100` = **244**.

**252 + 244 = 496.**

`en` sekiz kaydırma boyunca yüksek, `S` okunurken düşük.

Şimdi durup buna bak. Çözücüye şunların **hiçbiri** söylenmedi: devrenin
toplama yaptığı, operandların sekiz bit olduğu, karşılaştırma sabitinin 496
olduğu, hatta `en`'in ne işe yaradığı. Ona verilen tek şey `graph.json`'daki
hücre denklemleri ve "`S`, 8. çevrimde 1 olsun" kısıtıydı.

Ders 0'da başladığımız yeri hatırla: on binlerce dikdörtgen. Zincirin sonu bu.

---

## 7. Kapı: çözücüye inanmadan önce

Ve şimdi bu dersin metodoloji cümlesi:

> **Bir çözücü sonucu, model hakkında bir iddiadır — devre hakkında değil.**

Stage 6, geçiş bağıntısını `graph.json`'dan kuruyor. Bir defekt `graph.json`'da
ise, çözücü o defektli modeli kusursuz çözer ve kendinden emin, kendi içinde
tutarlı, **yanlış** bir cevap verir. Ve `graph.json`'ı okuyan hiçbir kontrol
bunu göremez — çünkü hepsi aynı bozuk alanı okuyor.

`sim/replay.py` bu yüzden var: trace'i **Stage 2'nin netlist'inden** geçiriyor
(`netlist.v`, Stage 3'ün `graph.v`'si değil), PDK'nın kendi Verilog modelleri
altında, Icarus'ta.

Netlist seçimi işin bütün özü. Stage 6 grafı çözdü; grafın kendi trace'ini
yine grafa karşı oynatmak sadece çözücüyü kontrol ederdi.

```
$ python tools/sim/replay.py warmup
cycle 0   S=x   model says S=0
cycle 2   S=0   model says S=0
...
cycle 8   S=1   model says S=1
  the property holds: S is 1 at cycle 8
RESULT: pass
```

(`S` ilk iki çevrimde `x`: simülasyon her flopu **bilinmeyen** başlatır, model
ise belirli bir yerden başladı. Bu yüzden yalnızca özellik çevrimi assert
ediliyor, kalanlar modelin tahmini yanında **raporlanıyor.** Özelliğin
adlandırmadığı bir çevrimde ortaya çıkan bir model hatası burada yakalanmaz —
ve bu, paketin doğrulanmamışlar listesinde yazıyor, üstü örtülmüyor.)

### İki kez gösterilen başarısızlık

**Bozulmuş trace.** 0. çevrimde `A`'nın tek biti çevrildi — operand 252 yerine
124 oluyor:

```
cycle 8   S=0   model says S=1
RESULT: fail                                          [exit 1]
```

**Bozulmuş model** — kapının asıl var oluş sebebi. `graph.json`'ın bir
kopyasında tek bir `cell_functions` girdisi değiştirildi: `xnor2_2`, xor diye
yazıldı (3 hücreyi etkiliyor). Sonra çözücü **o kopya üzerinde** koşturuldu:

```
$ python tools/stage6_invert.py warmup --graph out/warmup_tampered/graph.json
RESULT: pass, a trace was found                       [exit 0]     ← emin
$ python tools/sim/replay.py warmup --solution out/warmup_tampered/solution.json
cycle 8   S=0   model says S=1
RESULT: fail, the trace does not reproduce.           [exit 1]     ← yakalandı
```

Çözücü kendinden emindi, kendi içinde tutarlıydı ve yanlıştı. Pipeline'daki
başka hiçbir şey bunu fark etmezdi: Stage 6 modelini `cell_functions`'dan
kuruyor, yani o alandaki bir defekt aynı alanı okuyan her kontrole görünmez.
Simülasyon **başka bir yazarın başka bir dosyasını** okuyor, ve ikisi ancak
model doğruyken uyuşuyor.

---

## 8. `--post-reset`: soruyu doğru sormak

Yukarıdaki sağlamlık — "her açılış durumundan çalışır" — warm-up'tan türedi ve
warm-up **resete ihtiyaç duymuyor.** Puzzle'a taşınınca, yazarın sorulduğundan
daha zor bir problem çözülmüş oluyor: 92 serbest bit.

Duyuru ise şunu diyor (birebir alıntı, `docs/references.md` §6):

> "Don't forget to toggle `rst_n` before each input attempt."

`rst_n`'i yeni çevirmiş biri **keyfi bir durumda değildir.** Asenkron clear
taşıyan her flop 0'da, asenkron preset taşıyan her flop 1'de, sadece ikisi de
olmayanlar bilinmiyor. `--post-reset` bunları sabitliyor:

| | varsayılan | `--post-reset` |
|---|---|---|
| warm-up | 2^16 başlangıç durumu | **2^0** — 16 flopun 16'sı da `rst_n` taşıyor |
| puzzle | 2^92 | **2^4** — 92'nin 88'i sabit; 84 temiz, 4 kurulu |

İki mod da warm-up'ın cevabını aynı derinlikte (8) buluyor. Fark hızda: 25.7 s
/ 10 çağrı, karşısında 72.4 s / 28 çağrı — çünkü varsayılan mod 0'dan 7'ye
kadar sekiz trace bulup her birini karşı-örnekle çöpe atıyor. 16 yerine 92
flopta bu fark, koşmak ile beklemek arasındaki farktır.

Üç dürüstlük ayrıntısı:

- Kontrolün **seviyesi** bilerek sorulmuyor. Bu, resetin çekilip bırakılmasından
  *sonraki* durum; hangi polaritenin aktif olduğu hakkında bir iddia değil. Bir
  `dfrtp`, clear'ı ister yüksek ister düşük aktif olsun, 0'da çıkar.
- Hiçbir şey serbest değilse sağlamlık sorusu **boş bir soruya** dönüşür, ve
  araç bunu tam bu kelimelerle söylüyor — hak etmediği bir güvence basmıyor.
  Puzzle'da dört flop serbest kalıyor, yani orada gerçek bir soru.
- İki mod **iki ayrı dosya** yazıyor (`solution.json` ve
  `solution_post_reset.json`), çünkü farklı şeyler kanıtlıyorlar ve zayıf iddia
  güçlüsünün üstüne sessizce yazamaz.

Puzzle koşusu için doğru mod `--post-reset`: ipucunun tarif ettiği durum bu,
resmî test vektörünün başladığı durum bu, ve varsayılanın çözdüğünden kesinlikle
daha kolay bir problem. Varsayılan yine de varsayılan kalıyor, çünkü her
durumdan çalışan bir trace post-reset durumlarından da çalışır — tersi geçerli
değil.

---

## 9. Ölçek: puzzle'a yetecek mi?

Bu araç warm-up'ta 16 flop üzerinde çalıştı. Puzzle 92. Ve girdi seri, yani
derinlik büyük olacak — VCD'deki denemeler 121 bitlik.

Ders 5'in `scale_datapath` ailesi tam bunun için vardı: hedefi **çevreleyen**
boyutlar. Ölçüm:

| Tasarım | flop | hücre | derinlik | süre |
|---|---|---|---|---|
| warm-up | 16 | 79 | 8 (cevap) | 8.5 s |
| warm-up | 16 | 79 | **121** | **5.1 s** |
| scale16 | 90 | 280 | 16 | 8.3 s |
| scale16 | 90 | 280 | **121** | **13.9 s** |
| scale64 | 354 | 1136 | 32 | 17.9 s |

**Çözüm süresi derinlikte neredeyse düz.** Warm-up 121. derinlikte, 16.
derinlikte olduğu kadara mal oluyor. SMT2 dosyası doğrusal büyüyor — çevrim
başına bir netlist kopyası — ama z3 bu aralıkta umursamıyor. Süreyi asıl
belirleyen şey **sağlamlık turlarının sayısı**, çünkü her tur açılmış tasarımın
bir kopyası daha demek.

Okunacak satır `scale16` @ 121: 90 flop (puzzle 92), tek bitlik seri giriş
(puzzle'ın `I`'si gibi), 121 çevrim (bir denemenin uzunluğu) → **14 saniye.**
Puzzle'ın 2.6 katı hücresi var, ama bu kanıta göre açmanın kendisi problem
değil.

---

## 10. Kendin dene

```bash
python tools/verify_equiv.py warmup             # kapı: referansa denklik kanıtı
python tools/stage6_invert.py warmup            # BMC -> out/warmup/solution.json
python tools/stage6_invert.py warmup --depth 6  # cevabın altında bir sınır
python tools/stage6_invert.py warmup --post-reset
python tools/sim/replay.py warmup               # kapı: trace'e inanmadan önce
```

Üç soru.

1. Çözücü, warm-up'ta 0'dan 7'ye kadar her derinlikte bir trace buldu ve
   hepsi atıldı. O trace'ler **yanlış** mıydı?
2. `replay.py` neden Stage 3'ün `graph.v`'sini değil Stage 2'nin
   `netlist.v`'sini kullanıyor? Aynı devre değiller mi?
3. `verify_equiv.py` iki netlist'in denk olduğunu kanıtlıyor. Buna rağmen
   `graph.json`'daki bir hücre fonksiyonu yanlış olabilir mi?

### Cevaplar

**1.** Hayır — hepsi sorulan sorunun **doğru** cevaplarıydı. Yanlış olan
soruydu: "başlangıç durumu serbestken success'i yükselten bir dizi var mı?"
Bunun cevabı gerçekten evet, ve gerçekten kullanışsız. Doğru soru "**her**
başlangıç durumundan success'i yükselten bir dizi var mı?" ve onun cevabı
derinlik 8. Bu, bu projede tekrar eden bir desen: bir sonuç kötüyse önce
sorunun kendisine bak.

**2.** Aynı devre olmaları **umulan** şey, kanıtlanan değil — ve kontrolün
değeri tam olarak orada. Stage 6, `graph.json`'dan model kuruyor; `graph.v` de
aynı `graph.json`'dan yazılıyor. İkisi aynı kaynağı okuduğu için, o kaynaktaki
bir defekt **ikisinde de aynı** görünür ve sadeleşir — kendi kopyanı kendine
karşı test etmiş olursun. `netlist.v` bir aşama önceki, bağımsız bir dosya, ve
PDK'nın kendi davranışsal modelleriyle simüle ediliyor. Bozulmuş `xnor2_2`
gösterisi tam bunu kanıtladı: model kontrolü geçti, simülasyon geçmedi.

**3.** Evet, olabilir — ve bu, miter'ın bilinçli olarak kapatmadığı boşluk.
`verify_equiv` iki netlist'i de **aynı** `celllib.py` üzerinden okuyor, yani
liberty okumasındaki bir hata iki tarafta birden görünür ve iptal olur. Miter
şunu kanıtlıyor: aynı durum, aynı bağlantı, aynı fonksiyonlar. "Bu fonksiyonlar
silikonu doğru tarif ediyor mu" sorusunu iki başka şey cevaplıyor:
`verify_functions.py` (PDK'nın davranışsal modellerine karşı 850 tam doğruluk
tablosu) ve replay kapısı (trace, o modeller altında simüle ediliyor). **Üç
kontrol, üç ayrı yönden** — ve hiçbiri tek başına yeterli değil.

---

## Sonraki ders

Elimizde artık `success`'i yükselten girdi dizisi var, ve ona güvenmemizi
sağlayan bir kapı.

Ama yarışmanın istediği şey bu değil. İstenen: *"The string value you recovered
from the chip"* — **çipten kurtardığın metin.**

Yani devreye doğru girdiyi verdikten sonra, `O[7:0]` çıkışından akanı yakalayıp
bayta, bayttan karaktere çevirmek gerekiyor. Duyuru bu bloğu şöyle tarif
ediyor: *"ilk tersine mühendislik adımlarında görmezden gelmek güvenli, ama
nihai cevabı almak için simüle etmen gerekecek."*

Ders 7 o adım — ve zincirin son halkası.
