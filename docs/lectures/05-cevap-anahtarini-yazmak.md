# Ders 5 — Cevap anahtarını kendin yazmak

> Numara aşamayı izliyor ama kronoloji farklı: bu ders, Ders 3'ten hemen sonra
> okunmalı. Ders 4 (dedektörler) bundan sonra gelir — çünkü Stage 4, Stage 5'in
> ürettiği test seti olmadan yazılamazdı. Sebebini bu ders anlatıyor.

Ders 3'ün sonunda bir söz vermiştik. Elimizde etiketli bir graf var: saatler,
resetler, koniler. Sıradaki iş "bu 738 kutu hangi bloklara ayrılıyor" sorusuna
cevap veren algoritmalar yazmak. Ve bir sorun var:

**Bir dedektörün doğru çalıştığını nereden bileceğiz?**

Puzzle'ın cevap anahtarı yok. Zaten olsaydı dedektöre gerek kalmazdı. Dedektör
"bu sekiz flop bir sayaçtır" dediğinde, bunu onaylayacak ya da yalanlayacak
hiçbir şey elimizde değil.

Çözüm: cevabını bildiğimiz devreleri **kendimiz üreteceğiz.** RTL'ini biz
yazarız, cevabını bir dosyaya not ederiz, aynı sentez akışından geçirir aynı
hücre kütüphanesine indiririz. Dedektör önce bunlarda çalışmak zorunda.

Spec bu sıralamada nettir: *"detectors written without a test set cannot be
validated"* — test seti olmadan yazılan dedektör doğrulanamaz. O yüzden Stage 5,
Stage 4'ten önce geldi.

Bu ders bittiğinde şunları biliyor olacaksın: bir test setinin neyi ölçüp neyi
ölçemeyeceğini, "held out" ne demek ve neden yetmez, bir cevap anahtarının
kendisinin nasıl yanlış olabileceğini, ve hiç yanılamayan bir kontrolün neden
hiçbir şey kontrol etmediğini.

---

## 1. Bir korpus neyi ölçebilir, neyi ölçemez

İlk itiraz baştan gelmeli: puzzle, tersine mühendislik için *tasarlanmış* bir
devre. Ders kitabındaki blokları içermek zorunda değil. Hangi aile listesini
yazarsak yazalım, "puzzle'ı kapsıyor" diye kanıtlayamayız.

Bu itiraza karşı üç şey yapıldı, ve hiçbiri "listeyi daha çok düşünmek" değil.

### Yapı değil, işlev

Sentez, yapıyı yeniden yazar ama **işlevi korur.** Toplayıcı diye yazdığın şey,
mapper'dan çıktığında ders kitabındaki toplayıcıya benzemeyebilir — ama hâlâ
toplar. O yüzden spec, iki tespit stratejisinden işlevsel olanı ("miter" —
iki devreyi karşı karşıya bağlayıp bir çözücüye "bunlar hiç farklı davranabilir
mi" diye sormak) daha güvenilir sayar.

Bunun bir sonucu var: korpus sadece test seti değil, aynı zamanda **referans
kütüphanesi.** Bir miter'ın karşılaştıracak bir şeye ihtiyacı var. Korpusta
olmayan bir yapı "açıklanamadı" diye bulunabilir; ama **adlandırılamaz.**

### Aynı devre, iki farklı eşleme

Yukarıdaki iddia ("işlev korunur, dedektör işleve bakmalı") test edilemezdi —
çünkü her devre tam bir kez sentezleniyordu. Bir toplayıcının *o belirli*
eşlemesini ezberlemiş bir dedektör, tam puan alırdı.

Şimdi her devre, tek bir ortak ön-eşleme netlist'inden **iki kez** eşleniyor:
normal akış ve `abc -fast`. Hangi düğmeyi çevireceğimiz ölçülerek seçildi:
`-D 250` (bir zamanlama hedefi) hiçbir şeyi değiştirmiyor — denenen her devrede
hücre karışımı aynı. `-fast` ise gerçekten yeniden yazıyor: `adder_w8`'de 6
tipte 24 hücre, 10 tipte 31 hücre oluyor ve carry zincirindeki `maj3`, puzzle'ın
kullandığı `a31o`/`a21oi` hücreleriyle değiştiriliyor.

Sonuç: devrelerin yarıdan fazlası iki eşlemede gerçekten farklı hücre karışımına
düşüyor, ve **her beyan edilen olgu her iki eşlemede de kontrol ediliyor.**
Sadece bir eşlemede doğru kalan bir olgu, devrenin değil o eşlemenin özelliğidir.

### Negatif kontroller

Sadece pozitif örneklerden oluşan bir korpus **duyarlılığı** ölçer,
**seçiciliği** asla. Somut hali: her yazmaca "sayaç!" diye bağıran bir dedektör,
sayaçlardan oluşan bir korpusta tam puan alır. Yanlış alarm verdiğini
gösterecek hiçbir devre yoktur.

O yüzden bazı devreler **bulunmamak için** var, ve `must_not_detect` listesi
taşıyor.

---

## 2. Katalog

Başlangıçta 93 devre, 21 aile, beş grup:

| Grup | Adet | Sorusu |
|---|---|---|
| pozitif | 71 | dedektör bunu bulabiliyor mu |
| negatif | 6 | bulmaması gereken yerde susuyor mu |
| bileşik | 4 | bloklar birbirine karışınca hayatta kalıyor mu |
| yapı | 9 | hedefin taşıdığı şekiller, ve bir kuralın *yanılabilmesi* için gereken şekiller |
| ölçek | 3 | hedefin boyutunda hâlâ doğru mu |

Aileler spec'in listesi — register, shift register, sayaç, akümülatör,
toplayıcı, çıkarıcı, karşılaştırıcı, mux, decoder, FSM, LFSR — artı iki ek:
`serial_adder` ve `crc`. Neden? Çünkü puzzle'ın `I` girişi **tek bit.** Ders
kitabı devreleri operandlarını paralel alır; hedefimiz seri alıyor. FSM hem
binary hem one-hot kodlamayla var — aynı makine iki ayrı yerleşimle — çünkü
sadece birini tanıyan bir dedektör makineyi değil **kodlamayı** öğrenmiştir.

Sonradan dört aile daha eklendi (hikâyeleri bölüm 6 ve 7'de): `warmup_twin`
(iki özdeş yazmaç), `adder_demo` (warm-up'ın kendi RTL'i), `mux2i_witness`
(elle yazılmış, sentezlenmemiş tek netlist), ve `streamer` — Ders 7'nin cevap
anahtarı, beyan edilmiş bir metni bayt bayt yayan iki devre. Bugünkü toplam:
**99 devre, 197 netlist.**

### Held out: her üçüncü varyant

Her ailenin her üçüncü varyantı geliştirmeden **saklanıyor**: geliştirme
sırasında onlara bakmak yok, sadece skorlamada kullanılıyorlar. Kural sabit —
rastgele çekiliş değil — ki "held out" her makinede, her koşuda aynı anlama
gelsin. Ve devre başına bir kez karar veriliyor: held-out bir devrenin iki
eşlemesi birlikte held-out kalıyor, yoksa devre öbür eşlemesi üzerinden
geliştirmeye sızardı.

Ama bunun neyi **çözmediğini** şimdiden söylemek gerek, çünkü ders 4'te
karşımıza çıkacak: held-out skorlama şu soruyu cevaplar — "dedektör, *gördüğü
bir ailenin* başka parametrelerine genelleşiyor mu?" Şunu cevaplamaz: "kimsenin
aklına gelmeyen bir aileye genelleşiyor mu?" İkincisi ölçülemez, ve puzzle tam
olarak ikinci türden olabilir.

---

## 3. Hedefe benzemek: varsayım değil, ölçüm

Her devre aynı Yosys akışından, aynı PDK'ya iniyor, sonra puzzle'ın geçtiği
aynı `stage3_graph.build`'den geçiyor. Netlist'te durup kalan bir korpus,
dedektörleri karşılaşacaklarından **farklı türde bir girdiyle** test ederdi.

Peki üretilen devreler hedefe gerçekten benziyor mu? Bu soru ölçüldü, ve ilk
sayı öğretici biçimde yanlıştı:

| Karşılaştırma | Örtüşme |
|---|---|
| Tam hücre adı (`a21oi_2`) | %4 |
| Mantık işlevi (`a21oi`) | **%91** |

Aradaki fark **sürüş gücü** (drive strength). Puzzle çoğunlukla `_2`
kullanıyor; korpus çoğunlukla `_1`, çünkü `abc` zamanlama kısıtı yoksa işi
gören en küçük hücreyi seçer. Sürüş gücü fiziksel bir seçimdir, işlevi
değiştirmez. Yani anlamlı sayı ikincisi — ama birincisi de değerli, çünkü şu
kuralı doğuruyor: **dedektörler soneki normalize etmeli, tam ada asla
eşleşmemeli.** Tam ada eşleşen bir dedektör hedefte %3 bulurdu.

Ölçüm iki gerçek boşluk da çıkardı, ikisi de kapatıldı:

**Saat tamponu yoktu.** Puzzle saatini 16 `clkbuf_8` dalıyla dağıtıyor; korpus
her flop'un `CLK`'sını doğrudan porta bağlıyordu. Bu, boşlukların en
tehlikelisiydi: puzzle'da **bir mantıksal yazmacın bitleri aynı saat netini
paylaşmıyor.** Floplari saat netine göre gruplayan bir dedektör, puzzle'ın 92
flopunu on altı parçaya bölüp hiçbir şey bulamazdı — ve bunun *olamayacağı* bir
korpusta tam puan alırdı. `clock_tree` ailesi bu yüzden var: bir mantıksal
yazmaç, birden çok saat netine yayılmış, küçük boyda.

(Bu boşluğu kapatırken Yosys'in `clkbufmap` geçidi iki ayrı yolla **sessizce
hiçbir şey yapmadı** — argüman sırası ters yazılınca da, hücreler `clkbuf_sink`
niteliğini taşımayınca da "başarılı" deyip tampon eklemedi. İki kez. Sessiz
başarısızlık bu projede bir tema, ve birazdan tekrar göreceğiz.)

**Sabit yoktu.** Puzzle altı `conb_1` hücresiyle on iki neti sabitliyor; korpus
hiç üretmiyordu. Sebep bozuk bir geçit değil, geçerli bir varsayımdı: sentez,
sabiti onu okuyan mantığın içine katlar, geriye eşlenecek bir şey kalmaz. Bir
sabit ancak bir **porta** ulaşıyorsa katlanamaz — `tied_outputs` ailesi o
şekli üretiyor.

---

## 4. Boyut: toplamların sakladığı sayı

Korpusun sayıları toplamda sağlıklı görünüyordu. Farklı bir soru sorunca
görünen şey:

| | flop | hücre |
|---|---|---|
| `scale_datapath` öncesi en büyük devre | 32 | 96 |
| **korpustaki medyan devre** | **4** | |
| puzzle | 92 | 738 |

Dört floplu devrelerde puanlanan bir dedektör, doksan iki floplu bir devre
hakkında çok az şey söyler. Ve iki maliyet doğrusal değil: N flopu yazmaçlara
gruplamak, ve SAT örneği koni derinliğiyle büyüyen bir miter.

`scale_datapath` ailesi cevabı **hedefi çevreleyerek** veriyor, yaklaşarak
değil:

| | flop | hücre | koni kökü | saat neti |
|---|---|---|---|---|
| `scale_datapath_w16_b8` | 90 | 280 | 197 | 8 |
| *puzzle* | *92* | *738* | *189* | *16* |
| `scale_datapath_w32_b8` | 178 | 561 | 389 | 8 |
| `scale_datapath_w64_b16` | 354 | 1136 | 773 | 16 |

90 ile 354 arasında bir şey kırılırsa, tek bir geç/kal olarak değil **eğilim**
olarak görünür. Hesapladığı şey bilerek sıradan — seri beslenen bir shift
register, onu toplayan bir akümülatör, sayaç, LFSR, tutmalı bir çıkış yazmacı,
küçük bir durum makinesi. Puzzle'ın *işlevine* benzetilmiş hiçbir şey yok —
o işlev bilinmiyor. **Sadece boyut ve şekil eşleştirildi**, ikisi de korpusun
ölçülebilir biçimde eksik olduğu şeylerdi.

İlk sürüm on altı dal beyan edip sekiz kullandı. Kalan sekiz tampon hiçbir şey
sürmüyordu, `opt_clean` onları sildi, ve `verify_corpus.py` beyan edilen sayıyı
netlist'le karşılaştırıp yakaladı. Cevap anahtarının kendisi de denetim altında
— bir sonraki bölümün konusu tam bu.

---

## 5. Cevap anahtarı da kontrol edilir

Şimdi bu dersin kalbine geliyoruz.

Korpusun her devresi bir `truth.json` taşıyor: üreticinin beyan ettiği genişlik,
reset tarzı, saat sayısı, yazmaç bölümlemesi. Stage 4'ün dedektörleri **buna
karşı** puanlanacak. Peki ya beyanın kendisi yanlışsa?

Bu soru kuramsal değil. `verify_corpus.py`, her beyan edilen olguyu Stage 3'ün
sentez sonucundan bağımsızca okuduğu değerle karşılaştırıyor — biri *istenen*,
öbürü *gerçekleşen*, ve uyuşmadıklarında hangisinin yanlış olduğu önceden
bilinemez. Bugünkü durumu:

```
99 devre, 197 netlist, 12 kural, 762 kullanım
RESULT: pass
```

### İlk koşusunda ne buldu

**Altı devre senkron reset beyan etmişti ve hiç reset taşımıyordu.** Üretici
`async_reset` ve `async_set` üzerinde dallanıyor, `sync` bir `else`'e düşüyor
ve o `else` ne reset mantığı ne reset portu üretiyordu. Bunlar cevap anahtarı:
dedektörler bunlara karşı puanlanacaktı, ve "reset yok" diyen **doğru** bir
dedektör yanlış sayılacaktı.

Bir cümleyi iki kez okumaya değer: **test seti, test edeceği şeyden önce kendisi
test edilmeseydi, dedektörleri yanlış cevaba doğru eğitecektik.**

### Kural say, olgu sayma

Kontrolün ilk manşeti "662 beyan edilmiş olgu doğrulandı" idi. Yanıltıcı bir
sayı: 662, on bir kural çarpı korpus boyu. Ve kuralların dördü **sabitti** —
beyan edilen değer hiçbir devrede değişmiyordu.

Neden önemli? Çünkü hep aynı cevabı onaylayan bir kural, o cevabı koşulsuz
döndüren bozuk bir implementasyonu da geçirir. **Hiç yanılamayan bir kontrol,
hiçbir şeyin kontrolü değildir** — ta ki bir şey onu değiştirebilene kadar. İki
yarım gerek: öbür cevabı üreten bir devre, **ve** onu raporlayabilen bir okuyucu.

`clock roots` kuralı hep 1'di — her devre tek saatliydi. Yani kök yürüyüşünün
sadece *az-birleştirme* hatası test ediliyordu; bütün saatleri tek köke
*çöktüren* bir yürüyüş hepsinden geçerdi. `two_clocks` ailesi bunun için var.

### Sabitlerden biri gerçek bir defekt çıkardı

`flops on an inverting clock path` her yerde sıfırdı. "Neden bu kural hiç
sıfırdan başka bir şey diyemiyor?" diye sorulunca cevap sadece "öyle devre yok"
değildi. **Stage 3 raporlayamazdı da:** bu kütüphane kombinasyonel çıkışı
parantezli yazar — `function : "(!A)"` — ve aktif seviye ifadenin ilk
karakterinden okunuyordu. Kütüphanenin 21 invertörünün **hepsi** buffer diye
sınıflanmıştı. Yürüyüş doğru kökü yine buluyordu (şeffaf hücreden iki türlü de
geçersin), sadece parite kayboluyordu.

> Sorunun bütün değeri burada: sabit bir kuralın *neden* sabit olduğunu sormak,
> bazen kuralın kör olduğunu gösterir. `inverted_clock` ailesi artık 0, 4 ve 8
> cevaplarını üretiyor, ve parite defekti düzeltildi.

### Selftest: her kural, kendi bozulmasına karşı

Ders 3'te "geçen ama hiç yanılamamış test kanıt değildir" demiştik.
`verify_corpus.py --selftest` bu cümleyi rutine çeviriyor: her kurala, tam da
onun yakalamak için var olduğu bozulma veriliyor — kök yürüyüşü silinmiş,
reset pinleri kaybolmuş, saat ters çevrilmiş, fazladan bir flop, iki saat
alanı birleştirilmiş...

Ve burada, bu dersin en güzel tuzaklarından biri: ilk selftest **"10 bozulmanın
10'u yakalandı"** diyordu ve doğruydu. Bir süre sonra soru öbür yönden soruldu:
peki 10 bozulma, 12 kuralın kaçını **tetikledi?** Cevap: yedisini. Beş kural
hiç yanılırken görülmemişti — aralarında Stage 4'ün skorlamasının dayandığı
kural da vardı.

> **Her bozulmanın yakalanması, her kuralın örtülmesi değildir.** Sorunun iki
> yüzü var ve sadece biri soruluyordu.

Bugün: 15 bozulma, 15'i yakalanıyor, **ve 12 kuralın 12'si en az birinde
tetikleniyor.** Çıktı bunu iki satır halinde ayrı ayrı söylüyor.

---

## 6. Tutma (hold) hikâyesi: yapısal arama neden kaybeder

Ders 3'te enable desenini görmüştük: D'nin önünde bir mux, bir bacağında
flop'un kendi Q'su. Korpus 46 enable beyan ediyor. Yapısal arama kaçını
buluyor?

**12.**

Kalan 34, beş ayrı yolla saklanıyor — hepsi kendi yazdığımız ground truth'a
karşı ölçülmüş:

| Şekil | Sentezin yaptığı |
|---|---|
| `register` | mux D'nin önünde hayatta — **bulunur** |
| `counter` | enable carry zincirine katlanır: `D[0] = q[0] ^ en`. Mux hiç yok |
| `accumulator` | toplanana kapılanır: `D = q + (en ? d : 0)` |
| `register` + senkron reset | mux var ama reset mantığı araya girmiş |
| `scale_datapath` | mux tamamen çarpanlara ayrılmış |

Sonuncusu genel durumdur, ilk satır istisnadır. Sıradan yazmaç mux'unu **veri
bacağı bir port olduğu için** korur. O bacak devrenin hesapladığı bir şey olur
olmaz, mapper seçimi o hesabın içine katlar — bir teknoloji eşleyicisinin işi
tam olarak budur. `D = en ? (acc ^ lfsr) : outr` tek bir `a21oi` hücresine
düşüyor, Q iki hücre geriden dolaşıyor. Desen listesini uzatan herkes buna
kaybeder.

Bu yüzden kural değiştirildi: "tutma bir mux olarak hayatta kalır" (sentez
hakkında bir iddia) yerine **"enable, tuttuğu flopların veri konisine ulaşır"**
(devre hakkında bir iddia, beş şeklin beşinde de geçerli). Yapısal sayı hâlâ
raporlanıyor ve onu yenen şekiller **adıyla** listeleniyor — yeni bir kaybetme
yolu çıkarsa orana karışmaz, koşuyu düşürür.

Not: "bu yapısal bir olgu, yorum değil" cümlesi Ders 3'te doğruydu ve hâlâ
doğru. Değişen şu: yapısal aramanın bir **alt sınır** olduğu artık ölçülmüş
durumda, ve "bu yazmaç tutuyor mu" sorusunun aslında *işlevsel* bir soru olduğu
kaydedildi. O soruyu tam çözmek Stage 4'ün çözücüsüne kalıyor.

---

## 7. Yabancı kalemler: warm-up'ın kendisi ve bir tanık

### `adder_demo`: yazarın yazmadığı tek RTL

Korpusun bir girişi sentetik değil. `adder_demo`, `puzzle/warmup/00_source.v`
**değiştirilmeden** — bu pipeline'ın yazarının yazmadığı tek Verilog, ve beyan
edilen `[8, 8]` bölümlemesi burada verilen bir karardan değil gerçek bir DEF
hiyerarşisinden gelen tek giriş. Aynı işlev Stage 3'e ikinci bir yoldan da
ulaşıyor: warm-up hedefi layout olarak Stage 1–2'den, bu ise RTL olarak
Yosys'ten geliyor.

İlk koşusunda bir boşluk buldu: **sentez akışında `flatten` yoktu.** Üretilen
96 devrenin hepsi tek modüldü, kimse fark etmemişti; `00_source.v` üç modül, ve
Stage 3 hâlâ `shift_register` instantiate eden bir netlist'le karşılaştı.
Doksan altı kendi yazdığımız devrenin bulamadığını, yazmadığımız tek devre
buldu. Korpusun temel sınırının minyatürü: **kendi yazdığın test, kendi kör
noktanı paylaşır.**

İkinci bulgusu hâlâ açık bir problem: aynı tasarım, iki eşleme, **üç farklı
yazmaç bölümlemesi.** `abc -fast` on altı tutmanın beşini katlıyor; kontrol
imzası tutma netini içeriyor; beş flop farklı imza alıyor. Bir yazmacın *bazı*
bitlerinde kaçırılan tutma, olmayan bir sınır **icat ediyor** — hepsinde
kaçırmaktan daha kötü, çünkü eksik grup insan tarafından yine okunur ama sahte
sınır yanlış yöne götürür.

### `mux2i_witness`: sentezlenemeyen tanık

Stage 3'ün tutma araması bir zamanlar mux'u adından buluyordu: `"mux2" in
cell`. Kütüphanede `mux2i` diye bir hücre var — **eviren** mux: `Y =
(!A0&!S) | (!A1&S)`. Q'su bir bacağa bağlı bir `mux2i`, tutmaz; **her çevrim
terser.** İsim testi onu kabul ediyordu.

Kural düzeltildi (Ders 4'te göreceksin: artık isme değil, liberty işlevinin
kofaktörüne bakılıyor). Ama reponun standardı şunu da istiyor: kural, bir şeyi
**reddederken görülmeli.** Ve burada bir incelik: `mux2i_witness` korpusun
sentezlenmemiş tek girişi, çünkü **hiçbir RTL onu üretmez** — tutma isteyen bir
sentezleyici `mux2` çıkarır. Tanık elle yazılmış, önceden eşlenmiş bir netlist:
bir `mux2i`, doğrudan bir D'nin önünde, Q bacakta. Eski kural onda sahte bir
tutma kaydediyor; yeni kural hiçbir şey kaydetmiyor. Defekt artık gösterilmiş,
sadece savunulmuş değil.

---

## 8. Dürüstlük bölümü: korpus hedefe bakarak şekillendi

Bu, ona karşı ölçülen her skorun üzerindeki bir sınırlamadır ve okuyucunun fark
etmesine bırakılmak yerine burada kayıtlıdır.

Katalog, puzzle'a karşı yapılan ölçümler üzerine defalarca genişletildi:

| Aile | Eklendi çünkü puzzle... |
|---|---|
| `clock_tree` | saatini 16 dala dağıtıyor |
| `tied_outputs` | altı `conb_1` taşıyor |
| `serial_adder`, `crc` | girdisini tek bitten alıyor |
| `scale_datapath` | 92 flop, 738 hücre |

İki savunma, bir taviz. **Şekil işlev değildir** — eklenenler korpusun
taşımadığı yapısal şekiller, puzzle'ın hesapladığı bir şey değil (o
bilinmiyor). **Alternatif daha kötüydü** — `clock_tree` olmasaydı saat netine
göre gruplayan dedektör tam puan alıp hedefte tamamen çakılırdı; hedefe
bakmayı reddetmek, daha zayıf bir korpus hakkında daha temiz bir iddia
korumaktı. **Ama skorlar bundan zayıflar ve yönü bilinir:** hedefe bakarak
genişletilmiş bir korpus, o hedefi kapsayışını olduğundan iyi gösterir.

Dürüst düzeltme tek: Stage 4'ün **kalan** (residue) raporu — adlandırılanı
değil, adlandırıl*amay*anı sayan sayı. Aile ekleyerek şişirilemez.

Bir de okunmaması gereken bir sayı var: %91'lik kelime örtüşmesi bir *kapsama*
tahmini **değildir**, ve bir süre öyle sunuldu. Tamamen `nand2`'den kurulmuş
bir blok kelimede %100 alır ve korpusun hesaplamadığı bir şeyi hesaplıyor
olabilir. Sayı başka bir iddiayı destekliyor (soneki normalize et, işleve bak)
ve artık limitleri her seferinde yanında basılıyor.

---

## 9. Kendin dene

```bash
python tools/stage5_corpus.py --list      # katalog, sentezlemeden
python tools/stage5_corpus.py             # 99 devre, 197 netlist -> synth/
python tools/verify_corpus.py             # cevap anahtari, Stage 3'e karsi
python tools/verify_corpus.py --selftest  # 15 bozulma, 12/12 kural
```

Üç soru.

1. Korpus neden her devreyi **iki kez** eşliyor? Tek eşleme neyi ölçemezdi?
2. Selftest'in ilk hali "10/10 yakalandı" diyordu ve bu doğruydu. Yine de
   neden yetersizdi?
3. Kelime örtüşmesi %91. Bu sayı neden bir kapsama garantisi değil, ve gerçek
   kapsama sayısı ne zaman, nereden gelecek?

### Cevaplar

**1.** Tek eşlemeli bir korpusta "dedektör işlevi tanıyor" ile "dedektör bu
eşlemenin hücre desenini ezberledi" ayırt edilemez. İki eşleme, aynı işlevin
iki farklı yapısal kılığı demek; 54/99 devre gerçekten farklı karışıma düşüyor.
Bir de bedava bir kontrol veriyor: beyan edilen her olgu her iki eşlemede
doğrulanıyor — sadece bir eşlemede doğru kalan olgu, devrenin değil eşlemenin
özelliği.

**2.** Çünkü soru iki yönlü ve tek yönü soruluyordu. "Her bozulma yakalandı"
bozulmalar hakkında; "her kural en az bir bozulmada tetiklendi" kurallar
hakkında. İlki doğruyken beş kural hiç yanılırken görülmemişti — yani o beş
kural için elimizdeki tek şey sessizlikti. Aynı hata deseninin küçük boyu,
Ders 3'ün `bool("false")` hikâyesinde de vardı: bir şey *çalışıyor görünmek*
ile *yanılabildiği gösterilmiş olmak* farklı durumlar.

**3.** Kelime örtüşmesi hücre dağarcığını ölçer, hesaplanan işlevi değil.
Korpus bir puzzle bloğunu ancak bir korpus devresi **aynı işlevi hesaplıyorsa**
adlandırabilir; hangi hücrelerden kurulduğu bunu belirlemez. Gerçek sayı,
Stage 4'ün dedektörleri koştuktan **sonra** çıkar: netlist'in ne kadarı
açıklanamadan kaldı — kalan raporu. O sayı aile ekleyerek şişirilemez, ve bu
yüzden dürüst tek kapsama ölçüsü odur.

---

## Sonraki ders

Artık cevabı bilinen 99 devremiz var, cevap anahtarları denetimden geçmiş,
bozulmalara karşı sınanmış.

Sıradaki soru Ders 3'ün sonundaki soru: **92 flop hangi yazmaçlara ayrılıyor,
ve bir gruplama önerisinin iyi olduğunu hangi sayıyla söyleriz?**

Ders 4'te göreceğiz ki bu sorunun tek bir cevabı yok — altı ayrı kriter var,
aynada birbirinin tersi biçimde yanılıyorlar, ve "en iyi skor alan" ile "gerçek
tasarımda doğru olan" aynı kriter değil. Skorlamanın kendisinin nasıl
yanıltabildiğini de orada göreceğiz: null modelin 109/137 aldığı bir metrikle,
0 aldığı bir metrik aynı tabloda yan yana duracak.
