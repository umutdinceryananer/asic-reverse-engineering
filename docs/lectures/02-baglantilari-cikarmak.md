# Ders 2 — Bağlantıları çıkarmak

Ders 1 bir cümleyle bitmişti:

> Boyut ve transistör sayısı sana hücrenin ne kadara mal olduğunu söyler, ne
> yaptığını söylemez. **İşlev bağlantılarda yaşar.**

Bu ders o bağlantıları çıkarıyor. Sonunda elimizde artık bir "yerleşim listesi"
değil, **devrenin kendisi** olacak: simüle edilebilen, çalıştırılabilen bir
netlist.

Bu dersin sonunda şunları biliyor olacaksın: bir *net*'in ne olduğunu, katman
merdivenini tersten nasıl tırmandığımızı, isimlerin nereden geldiğini, bir
netlist'i doğru mu diye nasıl kontrol edeceğini (ve neden "sayılar tutuyor"
demenin doğrulama sayılmadığını), ve layout'un asla söylemediği bir bilgiyi
nereden bulduğumuzu.

---

## 1. Net nedir

Ders 0'da metal parçalarını, kontakları, via'ları görmüştük. Şimdi tek bir soru
soruyoruz: **hangi metal parçası hangisine değiyor?**

Birbirine değen iletken şekiller elektriksel olarak **tek bir düğümdür**. Buna
**net** deniyor. Bir netin üzerindeki her nokta aynı gerilimdedir; devre
açısından hepsi aynı yerdir.

Yani "bağlantı çıkarmak" dediğimiz şey aslında şu: layout'taki yüz binlerce
poligonu, birbirine değenler aynı kümede olacak şekilde **gruplara ayırmak.**

Buradan çok önemli bir sonuç çıkıyor, dersin geri kalanının yarısı buna
dayanıyor:

> **Bir netlist, pinlerin bir bölünmesidir (partition).**

Devrede 230 hücre var, her hücrenin birkaç pini var. Netlist, bu pin kümesini
ayrık gruplara bölüyor. Aynı gruptakiler birbirine bağlı, farklı gruptakiler
değil. Netlist'in *tamamı* bu bilgiden ibaret.

İsimler bu bilginin parçası değil. `n00042` ile `carry_out` aynı devredir. Bunu
şimdi aklında tut, doğrulama bölümünde geri geleceğiz.

---

## 2. Merdiveni tersten tırmanmak

Ders 0'da bir merdiven görmüştük:

```
diff/poly  →  licon1  →  li1  →  mcon  →  met1  →  via  →  met2  →  via2  →  met3 ...
 (cihaz)     (kontak)  (yerel)  (kontak)        (via)          (via)
```

O zaman aşağıdan yukarı, transistörden metale doğru bakıyorduk. Şimdi tersini
yapıyoruz: metalden aşağı inip **hangi hücre pinine vardığımızı** bulacağız.

Kullandığımız araç KLayout'un `LayoutToNetlist` sınıfı. Değen şekilleri
birleştirmeyi, via'dan yukarı çıkmayı, pin çözmeyi zaten biliyor; bunu sıfırdan
yazmak takvimin iyi bir kullanımı olmazdı.

**Ama bilmediği bir şey var: bizim prosesimizin katman merdiveni.** Ve buradaki
varsayılan ayarlara güvenmek tehlikeli. Neden tehlikeli olduğunu görmek önemli:

| Kural nasıl yanlışsa | Ne olur | Nasıl fark edilir |
|---|---|---|
| Fazla **cömert** (bağlanmaması gerekeni bağlar) | Ayrı netler birleşir, kısa devre | Zor. Netlist küçülür ama yapısı hâlâ makul görünür |
| Fazla **cimri** (bağlanması gerekeni bağlamaz) | Netler parçalanır, pinler havada kalır | Zor. Netlist büyür ama yine makul görünür |

İkisinin de ortak özelliği şu: **yapısal olarak makul, işlevsel olarak yanlış**
bir netlist üretirler. Bakınca "eh, olabilir" dersin. Bu yüzden merdiveni tahmin
etmiyoruz, açıkça yazıyoruz — [tools/stage2_nets.py](../../tools/stage2_nets.py)
içinde, `STACK` listesinde:

```
li1 --mcon--> met1 --via--> met2 --via2--> met3 --via3--> met4 --via4--> met5
```

Her routing katmanı **kendisine** bağlı (değen şekiller birleşsin diye) ve bir
**üstündeki via'ya** bağlı (kat çıkabilelim diye). Merdiven bu iki kuraldan
ibaret.

### `li1` neden listede

Kritik detay. `li1` (local interconnect) **standart hücre pinlerinin yaşadığı
katman**. Onu listeden çıkarırsan merdiven met1'den başlar ve hiçbir hücreye
ulaşamazsın — 230 hücrenin hepsi netlist'ten kopar. Ders 0'da hücrelerin
içindeki mor şekilleri hatırla; pinler orada.

### Dışarıda bıraktıklarımız

`poly`, `diff`, `licon1` ve kuyular **bilerek** listede yok.

Bunlar hücrenin *içi*. Biz hücreleri "pinleri olan kara kutular" olarak ele
alıyoruz — Ders 1'de kimliklerini zaten çözdük, ne yaptıklarını PDK'dan
biliyoruz. İçlerini de izlersek transistör seviyesinde bir netlist çıkarmış
oluruz; oysa bize kapı seviyesinde olan lazım.

Bu bir kayıp değil, bir **soyutlama seçimi**: doğru soyutlama seviyesini seçmek
tersine mühendisliğin işidir. Transistörlere inmek daha "derin" görünür ama
Stage 3'ün istediği şey değil.

### Merdiven doğru mu? Ölçelim

Yukarıda "merdiveni tahmin etmiyoruz, açıkça yazıyoruz" dedim. Güzel bir cümle
ama tek başına bir kanıt değil: açıkça yazılmış bir merdiven de yanlış olabilir.

Ölçmenin yolu basit. **Bir katmanı çıkar, çıkarımı tekrar yap, kaç net
değişiyor say.** Bağlantı taşıyan bir katman çıkınca netler kırılır; taşımayan
bir katman çıkınca hiçbir şey olmaz.

[tools/stack_sensitivity.py](../../tools/stack_sensitivity.py) bunu yapıyor.
Warm-up'ta:

```
full stack: 86 nets carrying a cell pin

dropped    nets  unchanged   broken
met5         86         86        0
met4        121         82        4
met3        111         75       11
met2        287          7       79
met1        529          4       82
li1          90          2       84
```

Bu tablo çok şey söylüyor.

**Aşağı indikçe hasar büyüyor.** `met4` çıkınca 86 netin 4'ü bozuluyor, `met1`
çıkınca 82'si. Mantıklı: alt katmanlar hücrelere yakın, üstteki her şey onların
üzerinden geçiyor.

**Net sayısının artması bozulma işaretidir.** `met1` olmadan 529 net çıkıyor —
baseline'ın altı katı. Daha çok net "daha çok bilgi" değil; bir netin
parçalanması demek. Bölüm 2'nin başındaki "fazla cimri" satırı tam olarak bu.

**`li1` çıkınca 84 net kırılıyor**, yani neredeyse hepsi. Hayatta kalan iki net
`VPWR` ve `VGND`, çünkü besleme hücrelere `met1` rayları üzerinden de ulaşıyor.
Üstelik kalan pinlerin **isimleri de gidiyor** — pin etiketleri 67/5'te, yani
li1'in üstünde duruyor, o yüzden pinler `$0`, `$2` diye isimsiz çıkıyor.

**Ve `met5` hiçbir şey bozmuyor.** Sıfır. Bu layout'ta met5 hiç sinyal
bağlantısı taşımıyor.

Bu son satır ilk bakışta "gereksiz bir katman koymuşum" gibi okunuyor. Ama
düşünürsen tercih doğru: merdiveni **ihtiyaçtan geniş** tutmak, dar tutmaktan
güvenlidir. Geniş merdiven boş yere bir katmana bakar; dar merdiven bir teli
sessizce koparır. Puzzle daha büyük bir tasarım ve üst metalleri kullanıyor
olabilir; met5'i şimdi çıkarsam, orada fark etmeden bağlantı kaybederdim.

---

## 3. İsimler nereden geliyor

Çıkarıcı kendi başına bıraksan netlere `$1`, `$2`, `$422` gibi isimler verir.
Bunlar bir işe yaramaz.

Ama layout'ta **metin etiketleri** var. Tasarım araçları net isimlerini
katmanların üstüne yazı olarak bırakır, ve bunlar GDS'te hayatta kalır:

| Metin katmanı | Bağlandığı |
|---|---|
| 67/5 | `li1` |
| 68/5 | `met1` |
| 70/5 | `met3` |
| 71/5 | `met4` |
| 72/5 | `met5` |

Çıkarıcıya "şu metin katmanını şu metal katmanına iliştir" dediğimizde, bir
etiketin üstünde durduğu net o ismi alıyor.

Bunun bize kazandırdığı şey büyük: **hücrelerin pin isimleri geliyor.**
`nand2_2` kutusundan `A`, `B`, `Y`, `VPWR`, `VGND` diye pinlerle çıkıyor;
`dfrtp_2` `CLK`, `D`, `Q`, `RESET_B` diye. Yani hangi şeklin hangi pin olduğunu
geometriden tahmin etmemiz gerekmiyor.

Warm-up'ta 8 net isimli çıktı: `A`, `B`, `S`, `clk`, `en`, `rst_n`, artı iki
besleme rayı `VPWR` ve `VGND`. Yani devrenin **bütün portları**. Geri kalan 78
net iç bağlantı, isimsiz.

---

## 4. Hiyerarşiyi neden koruduk

Çıkarımı iki türlü yapabilirdik.

**Düzleştirerek:** bütün hücreleri açıp içeriğini üst seviyeye dök, tek bir
poligon denizi elde et, hepsini birlikte çöz. Kavramsal olarak basit.

**Hiyerarşik:** her standart hücreyi kendi devresi olarak çöz, sonra üst seviyede
bu kutuları birbirine bağla.

İkincisini seçtik, iki sebeple. Birincisi hız — puzzle'ın 119 bin poligonunu tek
seferde çözmek yerine 437 küçük hücreyi bir kez çözüyorsun. İkincisi ve daha
önemlisi: **çıktının şekli.** Hiyerarşik çıkarımda üst seviye netlist zaten "hücre
pinleri üzerinde bir graf" oluyor; Stage 3'ün istediği tam olarak bu.

Bunun güzel bir yan etkisi var. Hücrelerin **iç düğümleri kendi içlerinde
kalıyor.** Çıkarıcıya `nand2_2`'yi soralım:

```
sky130_fd_sc_hd__nand2_2: pins ['VGND', 'VPWR', 'Y', 'B', 'A']
   net VGND     pins=['VGND']
   net VPWR     pins=['VPWR']
   net Y        pins=['Y']
   net B        pins=['B']
   net A        pins=['A']
   net $6       pins=[] internal      ← isimsiz, dışarı çıkmıyor
```

Beş pin, beş net, artı **bir tane isimsiz iç net.**

Şimdi Ders 0'ı hatırla. NAND2'nin layout'una bakmış ve şu soruyu sormuştuk:
hiçbir raya değmeyen, hiçbir pin taşımayan o mor `li1` şekli ne? Cevabı elle
bulmuştuk: **iki seri NMOS'un arasındaki düğüm.** Dışarıya çıkmaz çünkü
dışarıyı ilgilendirmez; ama NAND'ı NOR'dan ayıran şey tam olarak odur.

İşte `$6` o düğüm. Ders 0'da gözle bulduğumuz şeyi, bambaşka bir yöntem — layout
çıkarımı — kendi başına buldu ve "bu içeride kalır" diye işaretledi.

> **İki bağımsız yol aynı sonuca çıkıyorsa sonuç doğrudur.** Ders 1'de de aynı
> şey olmuştu (katman yokluğu vs. boolean kesişim). Bu projede en çok işe yarayan
> alışkanlık bu.

Karşılaştırma için `dfrtp_2` (flip-flop) 6 pin ve **8 iç net** ile geliyor.
Sekiz iç düğüm — içeride ciddi bir makine var. Ders 1'de 30 transistör saymıştık,
tutuyor.

---

## 5. Kutuları Stage 1'e bağlamak: pahalı bir hata

Çıkarıcı bize "şu konumda, şu yönelimde bir `nand2_2` alt devresi var" diyor.
Stage 1 de bize "şu konumda, şu yönelimde `i00379` numaralı instance var" diyor.
Bu ikisini eşleştirmemiz lazım.

İlk yazdığım kod **konumu anahtar olarak kullandı.** Mantıklı görünüyor: aynı
yerde iki hücre olamaz, değil mi?

Olur. Çünkü:

> **GDS'te bir yerleşimin koordinatı, hücrenin kendi orijininin nereye
> düştüğüdür — sol alt köşesinin değil.**

Bunu Ders 1'de DEF karşılaştırması için zaten öğrenmiştik. Ama sonucunu tam
görmemiştim: hücre ters çevrilmişse orijininden **sola ve aşağı** doğru uzanır.
Yani iki farklı hücre, farklı yönlerde uzanarak, aynı orijini paylaşabilir.

Warm-up'ta ölçtüm:

```
instances                 230
distinct origins          178      ← 52 tanesi çakışıyor
distinct (origin, orient) 230      ← ikisi birlikte tekil
```

Gerçek bir çakışma, tek bir noktada üç yerleşim:

```
origin (69.92, 38.08) üç kez kullanılmış:
      sky130_fd_sc_hd__nor2_2   FN
      sky130_fd_sc_hd__and2_2   S
      sky130_fd_sc_hd__and2_2   N
```

### Hata nasıl göründü

Şimdi bu hatanın **belirtisine** dikkat et, çünkü asıl ders orada.

Net sayısı doğruydu. 86 net, DEF de 86 diyor. Fanout dağılımı makuldü. Netlist
dosyası tamamen normal görünüyordu.

Tek anormal şey şuydu: `B` neti, bir `dfrtp_2` hücresinin `A1` pinine
ulaşıyordu.

`dfrtp_2` bir flip-flop. `A1` diye bir pini **yok**. DEF'e baktım: o net gerçekte
bir `mux2_1`'in `A1` pinine gidiyor. Yani çıkarıcı doğru pini bulmuş, ben onu
yanlış instance'a yapıştırmışım.

Eğer o iki hücrenin pin isimleri tesadüfen uyuşsaydı, hata hiçbir belirti
vermeden geçecekti — ve devre yanlış olacaktı.

### Düzeltme, ve fazladan bir kontrol

Anahtar artık **konum ve yönelim birlikte**. Ama bir şey daha ekledim:
eşleştirme yaparken Stage 1 ile çıkarıcının **aynı hücre tipinde anlaşıp
anlaşmadığını** kontrol ediyorum. Anlaşmazlarsa program duruyor.

Bu bedava bir çapraz kontrol: iki bağımsız yol (geometrik parmak izi ve layout
çıkarımı) 230 ve 1618 yerleşimin her birinde aynı cevabı vermek zorunda. Şu an
veriyor.

---

## 6. Doğrulama: "sayılar tutuyor" doğrulama değildir

Ders 1'de bunu bir kez söylemiştim. Burada daha da kritik.

Elimizde warm-up'ın DEF dosyası var, yani cevap anahtarı. DEF'in `NETS` bölümü
her neti tek tek, hangi pinlere değdiğiyle birlikte yazıyor.

Naif kontrol şu olurdu: "84 net buldum, DEF de 84 diyor, tamam." Bu **hiçbir
şey** doğrulamaz. İki neti birbirine karıştırmış olabilirim, sayı yine 84.

### Doğru kontrol: bölünme eşitliği

Bölüm 1'deki tanımı hatırla: bir netlist, pinlerin bir bölünmesidir. Öyleyse
kontrol de bir bölünme kontrolü olmalı:

> İki net **aynı nettir** ⟺ aynı `(instance, pin)` çiftleri kümesini taşıyorlar.

Yani her neti isminden bağımsız olarak, taşıdığı pin kümesine indirgiyoruz, ve
bizim kümelerimiz DEF'in kümeleriyle **birebir eşleşiyor mu** ona bakıyoruz.

İsim üzerinden eşleştirmiyoruz, ve bu bilinçli bir tercih. Biz bir netin ismini
ancak üstünde etiket varsa öğrenebiliyoruz — 84 netin sadece 6'sında var. İsimle
eşleştirmeye kalksak 78 neti hiç kontrol edememiş olurduk.

Instance isimleri de GDS'e taşınmıyor, o yüzden bizim `i00379` gibi
numaralarımızı DEF'in isimlerine **konum üzerinden** köprülüyoruz — bileşen
kapısının zaten doğruladığı yerleşim listesini kullanarak.

### Sonuç

```
=== components ===
DEF declares 230, parsed 230; stage 1 gives 230
exact matches 230/230

=== nets ===
DEF declares 84 signal nets and 2 special nets
stage 2 gives 86 nets carrying a cell pin
signal nets matched exactly 84/84
  recovered nets with no DEF counterpart: 0
  DEF nets not recovered:                 0
```

84'ün 84'ü, bağlantı bağlantı.

### Çıktıdaki iki ayrıntı

**Besleme netleri ve `*` jokeri.** DEF'te güç netleri her instance'ı tek tek
yazmaz, instance yerine `*` koyar: "her bileşen". Bu jokeri açmazsan iki pin
karşılaştırmış olursun; açınca netin gerçekten taşıdığı 460 pini
karşılaştırırsın.

**`VNB` ve `VPB` neden yok.** Bunlar *body tie*, yani transistörün gövdesinin
bağlandığı pinler. Hücreye **kuyular üzerinden** ulaşıyorlar, ve kuyular bizim
merdivenimizde yok (bölüm 2'de bilerek dışarıda bırakmıştık). Yani `li1`'den
yukarı tırmanan bir çıkarıcı onları hiç göremez.

Bu bir eksiklik değil — kapı seviyesindeki bir netlist zaten onları taşımaz.
Ama önemli olan şu: bunu **beklenen bir yokluk olarak raporluyoruz**, sessizce
görmezden gelmiyoruz. Rapor "230 tane `VNB` yok, olması da gerekmiyor" diyor.

> Sessizce atılan şey, ileride açıklanamayan hataya dönüşür. Ders 1'deki
> "eşleşmeyen her şeyi kaydet ve bak" kuralının aynısı.

---

## 7. Netlere bakmak: ne öğreniyoruz

Kapı geçti, artık çıktıya güvenebiliriz. Birkaç nete bakalım, çünkü bir netlist
okumayı öğrenmek de bu dersin parçası.

**En yüksek fanout'lu netler** (kaç pine dokunuyorlar):

```
en      16 pin    hepsi mux2_1 'S'        ← 16 mux'ın seçme girişi
rst_n   16 pin    hepsi dfrtp_2 'RESET_B' ← 16 flip-flop'un reset'i
$66      9 pin    8 x dfrtp_2 'CLK' + 1 x clkbuf_16 'X'
```

Üçüncü satır çok şey anlatıyor. Bir tane `X` (çıkış) ve sekiz tane `CLK` (giriş).
Yani **bir süren, sekiz dinleyen.** Bu bir saat dalı: `clkbuf_16` tamponu sekiz
flip-flop'un saatini sürüyor. Ders 1'de `clkbuf_16`'nın neden 40 transistörlü
olduğunu konuşmuştuk — işte sürdüğü yük burada, sayıyla.

Ayrıca dikkat: `rst_n` tam 16 `RESET_B` pinine gidiyor ve warm-up'ta tam 16
`dfrtp_2` var. Stage 1'in saydığı flip-flop sayısını, Stage 2 bambaşka bir yolla
teyit etmiş oluyor.

**En düşük fanout'lu netler**, tek pine dokunanlar:

```
S   1 pin    i00659 and4bb_2 'X'
B   1 pin    i00379 mux2_1  'A1'
```

Bunlar portlar. Diğer uçları başka bir hücre değil, **çipin kenarı**. `S` bir
çıkış (bir `X` pininden geliyor), `B` bir giriş (bir `A1` pinine gidiyor).

**Hiçbir pine dokunmayan netler:** warm-up'ta üç tane. Bunlar netlist'e hiç
girmiyor, çünkü devreyle ilgileri yok. Ne olduklarını Ders 0'da görmüştük:
met2'ye çizilmiş, hiçbir yere bağlanmayan **Jane Street logosu**.

Bunun logo olduğunu "öyle görünüyor" diye değil, ölçerek biliyoruz:

```
üst hücrenin kendi met2 poligonları: 1366
farklı boyut sayısı:                    1   -> hepsi 0.3 x 0.3 um
sınırlayıcı kutuları:  x 65.90..83.00, y 66.20..83.30
çipin sınırları:       x  0.00..100.00, y  0.00..100.00
```

**Bin üç yüz altmış altı özdeş kare**, 100 µm'lik çipin 17 µm'lik bir köşesine
sıkışmış. Yönlendirme böyle görünmez: gerçek teller farklı boy ve enlerde olur ve
çipin her yerine yayılır. Bu bir bitmap — piksel piksel çizilmiş bir resim.

Boşuna bir detay gibi görünüyor ama değil: "bağlantısız net" gördüğünde bunun bir
çıkarım hatası mı yoksa gerçekten devre dışı bir şey mi olduğunu bilmen gerekir.
Bu üç netin ne olduğunu bildiğimiz için **açıklanmamış hiçbir şey kalmadı.**

---

## 8. Layout'un asla söylemediği bilgi

Netlist'i Verilog'a çevirip simüle edeceğiz. Ve burada bir duvara çarpıyoruz.

Layout sana **hangi pinlerin bağlı olduğunu** söyler. Söylemediği şey: bunlardan
hangisi **süren**, hangisi **dinleyen**.

Yukarıdaki `$66` netine bak: `clkbuf_16.X` ile sekiz `dfrtp_2.CLK` aynı net.
Metal bunların hepsine eşit derecede değiyor. Ama devre açısından biri sinyali
üretiyor, sekizi tüketiyor. Bu **yön bilgisi** geometride yok.

Verilog'un ise buna ihtiyacı var.

### Kolay ama yanlış yol

İsimden tahmin edebilirdim. Bu kütüphanede `X`, `Y` ve `Q` çıkıştır, gerisi
giriştir. **Çoğunlukla** doğru çalışır.

"Çoğunlukla" tam olarak bir netlist'in yapısal olarak makul, işlevsel olarak
yanlış olma biçimidir. Bölüm 2'deki aynı tuzak, farklı kılıkta.

### Doğru yol: LEF

PDK sadece GDS yayınlamıyor. **LEF** dosyaları da var — hücrenin *soyut görünümü*:
ayak izi, pin konumları, ve bizim istediğimiz şey, **her pinin yönü.**

```
PIN Y
   DIRECTION OUTPUT ;
   USE SIGNAL ;
```

`tools/fetch_pdk.py` artık GDS'in yanında 437 `.lef` dosyasını da indiriyor, aynı
sabitlenmiş commit'ten. Hepsi parse ediliyor, yönü bilinmeyen tek pin yok, ve
LEF'in yazdığı `SIZE` değerleri Stage 1'de GDS'ten ölçtüğümüz ayak izleriyle
tutuyor — yine bağımsız iki kaynak, aynı cevap.

### Buradaki tuzak: `USE SIGNAL`

Pinleri filtrelemem gerekiyordu, çünkü besleme pinlerini Verilog'a yazmıyoruz.
İlk refleks: `USE SIGNAL` olanları al.

Doğru görünüyor. Değil.

Bu kütüphanede **69 pin `USE CLOCK` olarak işaretli.** Yani bu filtre, bütün
flip-flop'ların `CLK` bağlantısını **sessizce** siler. Netlist derlenir, simüle
olur, ve saatsiz flip-flop'lar hiçbir zaman veri yakalamaz.

Doğru kural ters yönden: **istediklerini seçme, istemediklerini çıkar.** Besleme
pinlerini (`USE POWER`, `USE GROUND`) at, kalan her şeyi al.

Bunu erken yakaladım — `dfrtp_2`'nin pin listesine baktığımda `CLK` yoktu ve
"bir flip-flop'un saati olmadan olmaz" dedim. Ders 0'dan beri kurduğumuz sezgi
tam da bu işe yarıyor: **beklediğin şey orada değilse dur.**

---

## 9. Verilog: netlist artık çalıştırılabilir

Bütün parçalar hazır. Portlar isimli netlerden geliyor (hücre içi etiketler kendi
devrelerinde kaldığı için üst seviyeye ulaşan tek etiket çipin kendi pin
geometrisindekiler). Port yönü ne sürdüğünden çıkıyor: net bir çıkış pinine
değiyorsa çip dışarı sürüyor, değmiyorsa çip sürülüyor.

Çıkan dosya ([out/warmup/netlist.v](../../out/warmup/netlist.v)) şöyle:

```verilog
module adder_demo (A, B, S, clk, en, rst_n);
  input A;
  input B;
  output S;
  input clk;
  input en;
  input rst_n;

  wire n00002;
  ...
  sky130_fd_sc_hd__clkbuf_16 i00005 (.A(clk), .X(n00070));
  sky130_fd_sc_hd__mux2_1    i00137 (.A0(n00015), .A1(n00036), .S(en), .X(n00079));
  sky130_fd_sc_hd__dfrtp_2   i00141 (.CLK(n00076), .D(n00080), .Q(n00018), .RESET_B(rst_n));
```

Layout'tan buraya kadar geldik. Bu dosya artık bir simülatöre verilebilir.

Warm-up'ın port listesi ve yönleri, `00_source.v` orijinaliyle **birebir** aynı.
Instance sayıları da hücre tipi tipine aynı: 79 mantık hücresi, sıfır fark.

230 yerleşimden 79'u çıkıyor çünkü geri kalanı fiziksel: dolgu, decap, kuyu
bağlantısı. İşlevsel pinleri olmadığı için Verilog'a yazılacak bir şeyleri yok.

Bir not: besleme pinlerini instance'lara yazmıyoruz. sky130 modelleri onları
sadece `USE_POWER_PINS` ile derlenince açıyor, ve warm-up'ın kendi referans
netlist'i de yazmıyor.

---

## 10. Asıl sınav: simülasyon

Şimdiye kadarki kontroller hep **yapısal**: doğru hücre mi, doğru bağlantı mı.
Ama asıl soru şu: **bu devre doğru şeyi hesaplıyor mu?**

Bunu ancak çalıştırarak öğrenirsin.

Kurulum: çıkardığımız netlist'i, PDK'nın kendi hücre modelleriyle birlikte Icarus
Verilog'da derliyoruz ve bir testbench'ten geçiriyoruz. Icarus pip paketi
olmadığı için bir Docker konteynerinde yaşıyor.

### Warm-up: 65536 girdinin hepsi

Warm-up devresi iki 8-bitlik sayı topluyor ve toplam 496 ise `success` veriyor.
Testbench **bütün operand çiftlerini** deniyor, örneklem değil:

```
pairs checked    65536
success asserted 15
mismatches       0
RESULT: pass
```

Neden hepsi? Çünkü sadece belirli bir elde (carry) deseninde ortaya çıkan bir
çıkarım hatası, rastgele 100 denemede kolayca hayatta kalır. Bütün uzay saniyeler
sürüyor; örneklem almanın hiçbir gerekçesi yok.

15 sayısı da kendi başına bir kontrol: `a + b == 496` ve iki operand da en fazla
255 ise, `a` 241 ile 255 arasında olmalı. Tam 15 değer. Simülatörün bulduğu sayı,
kâğıt üstünde hesaplanan sayı.

### Puzzle: yayınlanmış dalga formu

Puzzle'ın kendi cevap anahtarı yok. Ama `example_inputs.vcd` var: devreye neyin
sürüldüğünü **ve ne geri geldiğini** kaydeden bir dalga formu dökümü.

Yani bu bir duman testi değil, gerçek hedef üzerinde işlevsel bir kontrol.

```
cycles replayed      312
cycles compared on O  312
mismatches            0
cycles with success   0
RESULT: pass
```

Çıkardığımız netlist, yayınlanmış dalga formunu **bayt bayt** yeniden üretiyor.

---

## 11. Çalışan bir simülasyona giden dört tuzak

Bu bölüm uzun ama en faydalısı olabilir, çünkü dördü de **yanlış cevabı başka
bir problem gibi gösterdi.**

### Tuzak 1 — Docker BuildKit ağa çıkamadı

`docker build` içinde `apt-get` başarısız oluyordu; birebir aynı komut
`docker run` içinde çalışıyordu. `DOCKER_BUILDKIT=0` ile build geçiyor.

**Dürüst olmak gerekirse bu bir teşhis değil, bir atlatma.** Sebebini
bulamadım ve `CLAUDE.md`'de "bilinen boşluk" olarak yazılı duruyor. Bir şeyi
çözemediğinde yapılacak şey onu çözülmüş gibi göstermek değil, nerede
durduğunu yazmak.

İmajı da ikiye böldüm: `sim` sadece Icarus taşıyor, `eda` üstüne Yosys ve z3
ekliyor. Böylece Stage 3'ün ihtiyaçları için kurulan bir şey bozulduğunda
Stage 2'nin çalışan kapıları etkilenmiyor.

### Tuzak 2 — Bütün çıkışlar `x` çıktı

Simülasyon çalıştı ama her çıkış `x` (bilinmeyen). Netlist bozuk görünüyordu.

**Ne yaptım:** netlist'i düzeltmeye çalışmadım. Onun yerine **referans
netlist'i** (warm-up'ın orijinal, kesinlikle doğru olan `.v` dosyasını) aynı
testbench'ten geçirdim.

O da aynı şekilde `x` verdi.

Bu tek çalıştırma, "benim çıkarımım bozuk" ile "benim test düzeneğim bozuk"
sorularını ayırdı. Düzenek bozuktu.

Sebep: sky130 hücre modelleri varsayılan olarak *davranışsal* görünümü dahil
ediyor, o da `specify` blokları ve zamanlama kontrolleri taşıyor, ve zamanlama
verisi olmadan `x` tutuyor. Çözüm `-DFUNCTIONAL -DUNIT_DELAY=#1`.

> **Bir sonuç "neredeyse doğru" ya da "hiç çalışmıyor" olduğunda, önce düzeneği
> şüpheli gör ve onu bilinen-doğru bir girdiyle test et.** Test edilen şeyi
> geçene kadar oynamak, hatayı düzeltmez, saklar.

### Tuzak 3 — Veri yolu `z` çıktı

8 bitlik `O` çıkışı hep `zzzzzzzz` geliyordu, yani hiçbir şey sürmüyor.

Verilog'da bir isim `[A-Za-z_]` ile başlamıyorsa ters eğik çizgiyle kaçış
gerekir: `\my-net `. Emitter bu kuralı `O[0]`'a da uyguladı ve `\O[0]` yazdı.

Ama `\O[0]` Verilog'da **`O` vektörünün 0. biti değildir.** İçinde köşeli parantez
geçen, `O` ile hiçbir ilgisi olmayan, ayrı bir skaler sinyaldir. Yani `O`
veri yolunu hiçbir şey sürmüyordu — doğru olarak `z` gösterdi.

Doğrusu: bildirilmiş bir vektörün biti **seçim** olarak yazılır, `O[0]`, kaçış
kuralına hiç sokulmadan.

### Tuzak 4 — Çıkış bir çevrim geç göründü

Puzzle simülasyonu 20 uyuşmazlık verdi. Ama bayt dizisi **zaten tam olarak
doğruydu**, sadece bir çevrim kaymıştı.

Refleks çözüm: bir yere `+1` koy, geçsin. Bunu yapmadım, çünkü *neden* kaydığını
bilmeden koyulan `+1` doğru cevabı da yanlış sebeple verebilir.

Bunun yerine VCD'nin ham metnini açtım:

```
#1255000
b1010100 %      ← O 'T' oluyor
1!              ← clk yükseliyor
```

VCD sıfır gecikmeli bir döküm. Aynı zaman damgasında **çıkış değişimi, saat
değişiminden önce** listelenmiş. Yani saat kenarı geldiğinde anlık görüntü
alırsan, o kenarın *ürettiği* çıkışı zaten yakalamış oluyorsun.

Sezgisel olan seçim — "bir sonraki görüntüye bak" — bütün akışı bir çevrim
kaydırıyor. Kod bir satır değişti, ama o satırın **neden** öyle olduğu artık
[make_puzzle_stimulus.py](../../tools/sim/make_puzzle_stimulus.py) dosyasının
başında yazılı duruyor.

---

## 12. Bu dersin yöntem dersi

Ders 1 bir tavır dersiyle bitmişti: *eşleşmeyen her şeyi kaydet ve bak.* Bu
dersinki şu:

> **Ucuz ve kesin bir kontrol varken tahmin yürütme.**

Bu sekansta ödediğim en pahalı hata şuydu: `example_inputs.vcd`'nin sadece girdi
taşıdığını, sonuçları taşımadığını iddia ettim. Kaynağım bir README cümlesiydi.
Dosya 8 KB'lık düz metin, açmak iki saniye sürüyordu.

Yanlıştı. VCD çıkışları da taşıyor, ve içinde `TRY AGAIN` yazıyor. Bu yanlış
öncüle dayanarak üç ayaklı bir alternatif doğrulama stratejisi kurmuştum,
hepsini geri almak zorunda kaldım.

Aynı hatanın küçük kardeşleri de var: `docker build ... | tail` yazdım ve `tail`
başarılı olduğu için build'in başarılı olduğunu sandım, iki kez. Model dosyalarını
düzleştirdim çünkü birbirlerini nasıl include ettiklerine bakmamıştım.

Hepsinin ortak şekli aynı: **ikincil bir kaynaktan akıl yürütmek**, birincil olan
elimin altındayken.

Bunun karşıtı, bu sekansta gerçek hataları bulan alışkanlıktı: `dfrtp_2`'nin pin
listesine bakmak, referans netlist'i aynı düzenekten geçirmek, ham VCD'yi açmak.

İki pratik kural:

1. **Bir dosya hakkında bir şey iddia etmeden önce dosyayı aç.**
2. **Bir adımın bittiğini söylemeden önce ürettiği şeye bak** — çıkış koduna
   değil, dosyaya, satır sayısına, `docker images` çıktısına.

### Bu dersi yazarken aynı tuzağa iki kez düştüm

Dürüst olmak gerekirse bu bölüm sonradan eklenmedi, yaşandı.

**Birincisi.** Bölüm 14'teki "met5'i çıkarırsan ne olur" sorusuna önce
*cevabı yazdım*: "üst metaller çoğunlukla besleme dağıtımı ve uzun mesafe
yönlendirme için kullanılır, o yüzden etki sınırlı olur." Kulağa doğru geliyor
ve genel olarak da doğru bir cümle. Ama bu layout hakkında **ölçtüğüm** bir şey
değildi.

Ölçünce çıkan cevap "sınırlı" değil, **tam olarak sıfır**. Ve bu, tahminimden
daha ilginç bir cevap: merdivenin ihtiyaçtan geniş olduğunu, ve bunun güvenli
yön olduğunu söylüyor. Tahminimi yazsaydım hem yanlış hem de daha sıkıcı bir
ders vermiş olurdum.

**İkincisi, daha sinsi.** Ölçümü ilk yazdığımda netleri karşılaştırmak için
çıkarıcının kendi verdiği `subcircuit.id()` numaralarını kullandım. Çıkan tablo
şuydu:

```
without met5  ->  86 nets,  19 of 86 identical (67 changed)
```

86 net, 86 net. Sayı aynı. Ama 67 tanesi "değişmiş" görünüyor. Bu bir çelişki:
hiçbir net kaybolmamışsa 67'si nasıl değişir?

Buradaki refleks "demek ki met5 netleri yeniden düzenliyor" diye bir hikâye
uydurmak olurdu. Bunun yerine bölüm 11'deki alışkanlığı uyguladım: **aynı yığını
iki kez çalıştırdım.**

İki özdeş çalıştırma da birbirinden farklı çıktı. Yani sorun met5'te değil,
**benim karşılaştırma anahtarımdaydı**: `subcircuit.id()` her çalıştırmada
yeniden atanıyor, aynı hücreyi göstermiyor. Bölüm 5'teki "konum anahtar değildir"
hatasının birebir aynısı, farklı kılıkta: **yanlış anahtar seçmek.**

Anahtarı konuma çevirdim, ve tablo bölüm 2'de gördüğün temiz haline geldi.

Bu kontrol artık [stack_sensitivity.py](../../tools/stack_sensitivity.py)
içinde kalıcı: araç her çalıştığında önce aynı yığını iki kez çıkarıyor, sonuçlar
aynı değilse **duruyor** ve altındaki hiçbir sayıyı yazdırmıyor. Çünkü kararsız
bir anahtarla ölçülen fark, ölçüm değil gürültüdür.

> Bir karşılaştırma yapmadan önce, karşılaştırmanın kendisini bir şeyi
> **kendisiyle** karşılaştırarak test et. Sıfır fark vermiyorsa, ölçtüğün şey
> düzeneğin.

---

## 13. Nerede olduğumuzun özeti

| | warm-up | puzzle |
|---|---|---|
| Stage 1'e bağlanan yerleşim | 230 | 1618 |
| Hücre pini taşıyan net | 86 | 726 |
| bunlardan sinyal | 84 | 724 |
| etiketten isim alan | 8 | 15 |
| Hiç pin taşımayan net | 3 | 3 |
| En büyük fanout | 16 | 88 |
| Verilog'a yazılan instance | 79 | 738 |
| Port | 6 | 13 |

Puzzle'ın 738 instance'ı = 728 mantık hücresi + 10 `diode_2`. Diyotlar üretim
sırasında yük boşaltmak için var, hesap yapmıyorlar; ama gerçekten bir nete
bağlılar, o yüzden gizlemek yerine yazıp Stage 3'e "bunları role göre ele" diye
bırakıyoruz.

Küçük bir güzellik: puzzle'da `rst_n` neti 88 pine gidiyor — 84 tane `RESET_B`
artı 4 tane `SET_B`. Stage 1 puzzle'da 84 `dfrtp_2` ve 4 `dfstp_2` saymıştı.
İki aşama, iki bağımsız yöntem, aynı sayı.

### Dört kapı da geçiyor

| Kapı | Sonuç |
|---|---|
| Bileşenler, DEF'e karşı | 230/230 (tip, konum, yönelim) |
| Netler, DEF'e karşı | 84/84, bağlantı bağlantı |
| Warm-up simülasyonu | 65536 çift, 15 başarı, 0 uyuşmazlık |
| Puzzle simülasyonu | 312 çevrim, 0 uyuşmazlık |

### Bitmeyen bir iş

`docs/solver-pipeline.md` Stage 2 için bir **yedek çıkarıcı** istiyor: katman
başına değen poligonları union-find ile birleştiren, katmanlar arasını via
örtüşmesinden geçiren bağımsız bir uygulama.

Yazılmadı. Şu ana kadar ihtiyaç olmadı — net kapısı birebir tutuyor ve iki
simülasyon da geçiyor. Ama bu, ertelemek için bir sebep; **yapılmış saymak için
değil.** Boşluk olarak kayıtlı.

Aslında yapmak için ikinci bir gerekçe daha var, ve bu dersin tamamı onu
gösteriyor: bu aşamadaki her gerçek hata **bağımsız bir kontrol** sayesinde
ortaya çıktı. Farklı varsayımlarla yazılmış ikinci bir çıkarıcı, tam olarak o
tür bir kontrol.

---

## 14. Kendin dene

```bash
# Bagsiz bir venv'de, Docker gerekmeden:
python tools/stage1_cells.py warmup
python tools/stage2_nets.py  warmup
python tools/compare_def.py  warmup      # 230/230 ve 84/84 gormelisin

# Merdiven duyarlilik olcumu (bolum 2'deki tablo)
python tools/stack_sensitivity.py warmup

# Simulasyon (sim imaji gerekli)
DOCKER_BUILDKIT=0 docker build --target sim -t gds-teardown-sim -f docker/Dockerfile docker/
python tools/sim/run.py warmup           # 65536 cift, 0 uyusmazlik
```

Üç soru. Önce kendin düşün.

1. Bölüm 2'deki tabloya göre `met2`'yi merdivenden çıkarınca 86 netin 79'u
   bozuluyor — yani met2 ciddi miktarda bağlantı taşıyor. Ama bölüm 7'de üst
   hücrenin **bütün** met2 şekillerinin (1366 tanesinin) logo olduğunu ölçtük.
   Bu bir çelişki değil mi? Taşıyan met2 nerede duruyor?
2. Warm-up'ta 84 sinyal netinin sadece 6'sı isimli. Puzzle'da 724'ün 13'ü.
   Oran neden bu kadar düşük, ve daha fazla isim çıkarmanın bir yolu var mı?
3. Bölüm 7'de `$66` netinin bir `X` ve sekiz `CLK` taşıdığını gördük. Peki bir
   nette **iki tane** çıkış pini görsen ne düşünürdün?

### Cevaplar

**1.** Çelişki yok, ve cevabı GDS'in hiyerarşisinde: **bir hücrenin "kendi"
poligonları ile o hücrenin altında yaşayan poligonlar farklı şeyler.**

Warm-up'ın üst hücresinin doğrudan sahip olduğu şekiller şunlar:

```
üst hücrenin kendi poligonları:  met2 1366 (logo), met3 9, met4 6, met5 5, met1 1
her yerleşim toplandığında:      li1 1778, mcon 2718, met1 991, via 763,
                                 met2 508, via2 420, met3 200, via3 380
```

Yani yönlendirmenin neredeyse tamamı **yerleştirilmiş hücrelerin içinde**.
Standart hücreler `li1` ve `met1` şekillerini getiriyor; üst katmanlardaki
metali ise `VIA_*` hücreleri getiriyor. İçlerine bakınca ne oldukları çok net:

```
VIA_L1M1_PR_MR: li1 1, mcon 1, met1 1
VIA_M1M2_PR:    met1 1, via 1, met2 1
VIA_M2M3_PR:    met2 1, via2 1, met3 1
```

Her biri **tek bir via geçişi**: alt metal pedi, via, üst metal pedi. Ders 1'de
"869 `VIA_*` yerleşimi var, DEF bunları bileşen saymıyor" demiştik — işte
oldukları şey bu. Yönlendirici tel çizmiyor, hazır via bloklarını yan yana
diziyor, ve pedleri örtüştüğü için birleşiyorlar.

Bu yüzden bölüm 4'te hiyerarşiyi korumak bir tercih değil neredeyse zorunluluk:
düzleştirmeden bakan biri üst hücrede sadece logoyu görür ve "bu çipte
yönlendirme yok" der.

**2.** Çünkü etiketler *tasarım aracının bıraktığı yerde* duruyor, ve araç
genellikle sadece **portlara** isim yazar. İç netlerin ismi sentez sırasında
üretilmiş geçici isimlerdir (`_0123_` gibi) ve layout'a yazılmalarının bir
faydası yok, o yüzden yazılmıyorlar.

Daha fazla isim çıkarmanın yolu **yok** — ve bu önemli, çünkü işin doğasını
anlatıyor. Tersine mühendislikte isimleri geri getiremezsin; yapıyı geri
getirirsin, isimleri **sen** koyarsın. Stage 3 ve 4'ün bütün amacı bu: `n00042`
netine "bu bir sayacın 3. biti" diyebilmek. İsimden değil, **yapıdan.**

**3.** İki ihtimal var, ve ikisi de bilinmeye değer.

Ya devre gerçekten öyle — iki çıkış aynı tele bağlıysa buna *bus contention*
denir, biri 1 diğeri 0 sürerse kısa devre olur. Modern senkron tasarımda bu bir
hatadır (üç-durumlu tampon kullanılmadıkça, ki bu kütüphanede o hücreler
mevcut ama warm-up'ta yok).

Ya da **benim çıkarımım fazla cömert** ve birbirine değmemesi gereken iki neti
birleştirdim. Bölüm 2'deki ilk satır.

İkincisi çok daha muhtemel. Ve bu, netlist'e uygulanabilecek çok ucuz bir sağlık
kontrolü: *her sinyal netinde tam olarak bir çıkış pini olmalı.* Şu an bu kontrol
kodda yok; net kapısı DEF'e karşı geçtiği için ihtiyaç duyulmadı. Ama ground
truth'un olmadığı bir hedefte — yani gerçek bir tersine mühendislikte —
kullanabileceğin en iyi kontrollerden biri budur, çünkü **cevap anahtarı
gerektirmez.**

---

## Sonraki ders

Elimizde artık doğru olduğunu kanıtladığımız bir netlist var. Ama netlist,
devreyi *anlamak* için hâlâ ham bir biçim: 738 kutu ve 726 tel, hiçbirinin ismi
bir şey söylemiyor.

Stage 3 bunu **normalleştirilmiş bir graf**'a çevirecek: hücreler soyut kapılara
indirilecek, sıralı elemanlar ayrılacak, saat ve reset ağaçları işaretlenecek,
kombinasyonel mantık düzeltilecek. Amaç, üstünde desen aramanın mümkün olduğu
bir yapı elde etmek.

Çünkü asıl soru hâlâ cevapsız: bu 92 bitlik durum makinesi **ne hesaplıyor?**
