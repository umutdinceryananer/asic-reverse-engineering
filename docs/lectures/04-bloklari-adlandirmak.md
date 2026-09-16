# Ders 4 — Blokları adlandırmak, ve kalanı dürüstçe raporlamak

> Numara aşamayı izliyor ama kronoloji farklı: bu dersten önce **Ders 5'i** oku.
> Stage 4'ün dedektörleri, Stage 5'in korpusu olmadan doğrulanamazdı; dersler de
> o sırayla yazıldı.

Ders 3'ün sonunda elimizde etiketli bir graf vardı: saatler, resetler, koniler,
sabitler. Ders 5'te cevabı bilinen 99 devrelik bir test seti kurduk. Şimdi asıl
soruya dönüyoruz:

**Puzzle'ın 92 flip-flop'u hangi yazmaçlara ayrılıyor?**

Neden önce bu soru? Çünkü adlandırma, gruplamanın üstüne kurulur. "Bu sekiz
flop bir sayaçtır" cümlesi, "bu sekiz flop **bir şeydir**" cümlesi olmadan
kurulamaz. Ve düz bir netlist bunu söylemiyor: puzzle'ın 92 flopu beyan edilmiş
bir sırada değil, ortak bir isim altında değil, üstelik **on altı farklı saat
netinde** oturuyor.

Bu ders bittiğinde şunları biliyor olacaksın: bir yazmacı tanımlamanın altı
farklı yolunu ve neden hiçbirinin tek başına yetmediğini, bir bölümleme
önerisini puanlamanın üç yolunu ve bir metriğin nasıl yalan söyleyebildiğini,
ve "cevap veremiyorum" demenin ne zaman doğru cevap olduğunu.

---

## 1. Yazmaç nedir, ve altı aday tanım

Bir yazmaç (register), kaderi ortak bitlerin kümesidir: birlikte yazılırlar,
birlikte silinirler, bir kelimenin bitleridir. Ama netlist "kader" diye bir
alan taşımıyor. Onu gözlemlenebilir bir şeye çevirmek gerekiyor — ve çevirmenin
birden fazla yolu var.

### Aday 1: kontrol imzası

Bir yazmacın bitleri tanım gereği aynı saatten, aynı resetten, aynı tutma
sinyalinden sürülür. Öyleyse imzası: saat kökü + reset kökü ve seviyesi + set
kökü ve seviyesi + tutma neti. Aynı imzayı taşıyan floplar bir grup.

Zarif, ve **tanımdan** geliyor. Bir sorunu var, birazdan göreceğiz.

### Aday 2: bağlı bileşenler

Bir shift register'ın bitleri birbirine bağlıdır: her bitin verisi bir önceki
bitten gelir. Öyleyse flop-flop veri kenarlarından bir graf kur, bağlı
bileşenler yazmaçlardır.

Bunun sorunu tersten: **düz bir yazmacın bitleri birbirine hiç bağlı değildir.**
Sekiz bitlik bir tutucu yazmaçta her bit kendi verisini dışarıdan alır;
bileşenler onu sekiz teke parçalar.

### Aday 3: renk arıtma (colour refinement)

Her flopa komşuluğundan bir "renk" ver, komşu renklerine bakarak renkleri
arıt, sabitlenene kadar tekrarla. Grafın simetrilerini bulur.

Sorunu: bir shift register **zincirdir**, ve zincirde her bitin konumu
farklıdır. Öncüsü farklı renk alan her bit farklı renk alır — zincir tek tek
bitlere ufalanır.

### Aday 4: akış bölmesi (DANA'nın geçidi)

Literatürden geldi (DANA, TCHES 2020; `docs/references.md` §3). Fikir: bir
grubun içindeki her bitin verisi **hangi gruplara** gidiyor, **hangi
gruplardan** geliyor? Üyeleri farklı cevap veren grubu böl, sabitlenene kadar
tekrarla.

Güzel tarafı ölçüldü: düz bir yazmacı **bölmez** — bitleri aynı yerlere gider,
aynı yerlerden gelir. `register_w8_async_reset` akış bölmesinde `[8]` kalıyor,
bağlı bileşenlerde sekiz teke dağılıyor.

Kötü tarafı da ölçüldü, ve makalenin cümlesinin vaat ettiği şey değil: tek
başına sabit noktaya koşturulduğunda **zincirlerde teklere çöküyor** — bir
zincirde her bitin öncüsü farklı gruba düşer düşmez ayrışma durdurulamıyor:

| tur | warm-up | `warmup_twin_w8` |
|---|---|---|
| 1 | `[14, 1, 1]` | `[7, 7, 1, 1]` |
| 2 | `[12, 1, 1, 1, 1]` | `[6, 6, …]` |
| 4 | `[8, 1×8]` | `[4, 4, …]` |
| sabit nokta | 16 tek | 16 tek |

Bu DANA'nın yanlışlığı değil: DANA dokuz geçidi **çiftler halinde**, çoğunluk
oylamasıyla uygular ve hiçbirini tek başına sabit noktaya koşturmaz. Bizim
ölçtüğümüz, geçitlerden biri, tek başına — ve öyle raporlanıyor.

Ama bir şeyi başka hiçbir kriterin yapamadığı kadar iyi yapıyor. Puzzle'ın
R0'ına en çok benzeyen korpus devresi `scale_datapath_w16_b8`: 90 flop, yedi
beyan edilmiş yazmaç, ve kontrol imzası **82'lik tek blob** cevabı veriyor.
Akış bölmesi oradan `[16, 8]` + 66 tek çıkarıyor — ve o iki grup **eksiksiz
RTL yazmaçları.** Hangi kriterin kaç *bütün* yazmaç kurtardığı artık türetilmiş
bir kolon:

| Kriter | boyutlar | bütün yazmaç |
|---|---|---|
| kontrol imzası | `[82, 8]` | 0 |
| + bağlı bileşenler | `[56, 18, 8, 5, 3]` | 1 |
| renk arıtma | `[26]` + 64 tek | 0 |
| kontrol + akış bölmesi | `[16, 8]` + 66 tek | **2** |

(O kolonun bir de hikâyesi var: ilk hali "başka hiçbir kriter burada bütün bir
yazmaç üretemiyor" diye koşulsuz basılan bir *cümleydi*, ve basıldığı koşuda
iki ayrı yönden yanlıştı. Cümle silindi, yerine her koşuda yeniden hesaplanan
kolon geldi — `docs/problems.md` 48. Ders 5'in kuralı: ölçüm program değilse,
bir kez olmuş bir ölçümdür.)

### Aday 5: yerleşim yakınlığı

Şimdiye kadarki dört adayın hepsi **tellere** bakıyor. Beşincisi hiç bakmıyor:
çipin geometrisine bakıyor. Bir yazmacın bitleri fiziksel olarak yan yana
yerleştirilir — yerleştirici bunu zamanlama için yapar, ve puzzle'ın duyurusu
bunu açıkça söylüyor: *"The circuit is physically arranged to hint at its
functionality, so look closely at the layout!"*

Stage 1 zaten her yerleşimin köşesini ve yönünü kaydediyor. Kriter tek bağlantı
(single linkage): üç sıra yüksekliği (8.16 µm) içindeki floplar birleşir.

Warm-up'ta sonuç: **üyelik dahil doğru** — `sr_a`'nın sekizi bir kümede,
`sr_b`'nin sekizi öbüründe, iki küme arasında 21.76 µm boşluk. Tek bir tel
okumadan.

İki dürüstlük notu, ikisi de aracın kendi çıktısında: eşik bir sayı olarak
değil **profil** olarak basılıyor (1 sırada 16 tek, 2'de karışık, **3–8 arası
hep `[8,8]`**, 9'da `[16]`) ve 3, o platonun alt kenarı — **tek veri noktasına
oturtulmuş tek parametre**, saklanarak değil söylenerek. Ve korpus bunu
**puanlayamaz**: sentezlenen devrelerin yerleşimi yok. Örneklem büyüklüğü 1 —
warm-up — ve sonra, bir insanın okuyacağı puzzle.

### Ayna simetrisi

Tabloya topluca bak:

- kontrol imzası: hiçbir kontrol sinyalinin işaretlemediği sınırı **göremez**
- bağlı bileşenler: bitleri etkileşmeyen düz yazmacı **parçalar**,
  zincirlenmiş bir çifti (biri öbürünün girdisini hesaplıyorsa)
  **birleştirir** — `streamer` devrelerinde ölçüldü
- renk arıtma ve akış bölmesi: zinciri **parçalar**
- yerleşim: tel bilmez, ama n = 1

Biri bitlerin etkileşmesine muhtaç, öbürü etkileşmemesine. Bu bir ayar sorunu
değil; **kriterler tamamlayıcı, rakip değil.** Ve ilk sürümde tam bu hata
yapıldı: en yüksek skorlu kriter "seçildi" ve sıralama olarak sunuldu.
Neden yanlış olduğunu skorlama bölümü gösterecek.

---

## 2. Bir bölümlemeyi puanlamak — ve bir metriğin yalanı

Dedektörümüz bir bölümleme öneriyor: `[8, 8]` ya da `[16]` ya da başka bir şey.
Korpusun cevap anahtarıyla karşılaştıracağız. Nasıl?

### Yol 1: birebir eşleşme

Boyut kümeleri eşit mi? `[8, 8] == [8, 8]` → doğru, başka her şey → yanlış.

Basit, ve iki ayrı biçimde kör. Birincisi: 72 bitlik bir yazmacın 71'ini doğru
bilen cevapla hiçbirini bilmeyen cevap **aynı puanı** alır — kısmi başarı
"yanlış"a yuvarlanır. İkincisi daha sinsi: korpusun 137 netlist'inin 109'u
**tek yazmaç** beyan ediyor. "Her şey tek gruptur" diyen ve başka hiçbir şey
yapmayan bir kriter 109/137 alır.

Ders 5'in null model kuralı burada hayat kurtarıyor: skoru, hiçbir şey yapmayan
modelin skoru olmadan okumak yasak. Kontrol imzası 117/137. Null model 109/137.
Gerçek fark sekiz netlist.

### Yol 2: NMI ve saflık

Literatürün cevabı iki metrik. **NMI** (normalized mutual information):
önerilen gruplama, gerçek gruplamayla ne kadar bilgi paylaşıyor — 0 ile 1
arası. **Saflık** (purity): her önerilen grubun içi ne kadar tek tip.

NMI'nin güzelliği: tek-grup null modeli **0 alır.** Tek kümenin entropisi
sıfırdır; hiçbir şeyle bilgi paylaşamaz.

Ve şimdi bu projenin küçük ama örnek bir düzeltmesi. Plana şu cümle yazılmıştı:
"saflık da öbür dejenere cevabı — her flop kendi başına — öldürür." Kulağa
doğru geliyor. **Ölçüm: yanlış.** Tek kişilik her küme saftır; teklere ayırma
saflıktan tam 1.0 alır. Onu öldüren birebir eşleşmedir (7/137). Üç kolonun üçü
de basılıyor, çünkü üçü üç ayrı dejenereyi görüyor:

| | tek grup | her flop tek |
|---|---|---|
| birebir | 109/137 | 7/137 |
| NMI | 0.0 | 0.3879 |
| saflık | 0.5481 | **1.0** |

Tek-grup modelinin saflığı bir zamanlar tam **0.5** okunuyordu. O yuvarlaklık
bir tesadüftü: soruyu soran on netlist'in hepsi eşit yarımlar beyan ediyordu.
Ders 7'nin `streamer` devreleri `[7, 4]` ve `[7, 3]` beyan edince tesadüf
bozuldu. Dejenere bir modelin yuvarlak sayı alması, güvenmek için değil
şüphelenmek için bir sebeptir.

### 0/0 meselesi: kenar durumu değil, korpusun %80'i

NMI'nin bir tanımsızlığı var: gerçek cevap **tek sınıfsa** entropisi sıfır,
ve oran 0/0. Bu bir dipnot olurdu — 137 netlist'in 109'u tam o durumda
olmasaydı.

O 109'u ortalamaya 0 diye katarsan her kriter "korpusun %80'inde başarısız"
görünür; 1 diye katarsan her kriter "neredeyse kusursuz" görünür. İkisi de aynı
sebepten yanlış: **o netlist'ler soruyu sormuyor.** Karar: tek sınıf–tek grup
1.0 (bölümlemeler eşit, NMI'nin ölçtüğü tek şey bu); tek sınıf–bölünmüş cevap
tanımsız, ortalamadan çıkarılır ve kendi kolonunda sayılır.

Bunu görmezden gelirsen ne olur, ölçüldü: 123 satırlık "büyük ortalama"da
tek-grup null modeli 0.8862, kontrol imzası 0.8863 alıyor — **üç ondalıkta
aynı sayı** — çünkü 109 satır hiçbir zaman ayrışamazdı. İki ortalama basılıyor
ve okunması gereken ikincisi: gerçek cevabı birden çok sınıf taşıyan **14**
netlist üzerinden.

### Ve tersine dönen sıralama

Şimdi bu dersin ana tablosu. Aynı beş kriter, üç metrik:

| Kriter | birebir /137 | NMI | saflık |
|---|---|---|---|
| kontrol imzası | **117** | 0.001 | 0.5525 |
| renk arıtma | 101 | 0.419 | 0.8214 |
| kontrol + akış bölmesi | 91 | **0.5019** | 1.0 |
| kontrol + bağlı bileşenler | 80 | 0.3911 | 0.7623 |
| *null: tek grup* | *109* | *0.0* | *0.5481* |
| *null: her flop tek* | *7* | *0.3879* | *1.0* |

**Birebir eşleşme ile NMI, kriterleri ters sırada diziyor.** Birebir, kontrol
imzasını birinci yapıyor; NMI — yani sorunun gerçek olduğu 14 netlist —
kontrol imzasına 0.001 veriyor. Null modelin 0.0'ı, üç ondalıkla.

Ve bir uyarı daha, tabloyu okumadan önce: **NMI kolonunun sıralaması sağlam
değil.** Bu tablo bir zamanlar bağlı bileşenleri 0.5476 ile tepede
gösteriyordu. Ders 7 için korpusa iki `streamer` devresi eklendi — soruyu
soran 14 netlist'in dördü artık onlar — ve o devrelerde renk arıtma **tam
doğru** cevabı verirken bağlı bileşenler tek grup diyor: indeks yazmacı ROM'u,
ROM da çıkış yazmacını besliyor, yani ikisi gerçekten bağlı. Warm-up'ın tam
aynadaki hali. Dört netlist sıralamayı çevirdi; hiçbir şey ayarlanmadı.
Kolonu **14 netlist üzerinde bir sıralama** olarak oku, kesinleşmiş bir
hüküm olarak değil.

Cümleyi tam ağırlığıyla kur: **Stage 4'ün var olma sebebi olan soruda, ilk
seçilen kriter null modelin kendisidir.** Birebir sıralama, soruyu sormayan
109 netlist'in ürettiği bir yanılsamaydı.

> Metodoloji cümlesi: **skor, sorulan sorunun skorudur.** Metriğini seçmeden
> önce hangi soruyu sorduğunu yaz; sonra null modeli aynı tabloya koy. İkisini
> de yapmayan her skor, bir şey ölçüyormuş gibi yapar.

(Bir uygulama detayı, aynı disiplinden: NMI ve saflık kodu, `verify_functions`
'ın el tabloları gibi **elle hesaplanmış yedi satırlık bir tabloya** karşı her
koşuda sınanıyor, ve `--score` ölçmeye başlamadan önce o tablodan geçmek
zorunda. Yanlış normalizasyon, 0/0'ı ortalamaya katmak, beyana uydurulmuş
üyelik — üçü de bilerek denendi, üçü de yakalanıyor.)

---

## 3. Warm-up: cevabın bilindiği yerde Stage 4 yanılıyor

Beş aşama boyunca repoda okunmadan duran bir cevap anahtarı vardı
(`docs/problems.md` 34): `03_post_place_and_route.def`, her yerleşime geldiği
hiyerarşinin adını yazıyor — `sr_a/_16_`, `add0/_31_`. Gerçek bir tasarımın
**kesin blok bölümlemesi.** Bizim yazdığımız korpus değil; gerçek cevap.

`verify_blocks.py` onu kurtarılan instance'lara eşliyor (konum + yön + hücre,
230/230) ve söylediği şu:

```
sr_a  16 hücre, 8'i flip-flop        kontrol imzası      [16]      YANLIŞ
sr_b  16 hücre, 8'i flip-flop        bağlı bileşenler    [8, 8]    DOĞRU
add0  41 hücre                       renk arıtma         [16]      yanlış
cmp0   3 hücre                       yerleşim            [8, 8]    DOĞRU
gerçek bölümleme: [8, 8]
```

İki özdeş sekiz bitlik shift register; **saatleri, resetleri ve enable'ları
ortak.** Hiçbir kontrol imzası onları ayıramaz — ayıracak sinyal yok. Ve
korpus skorunun *sonuncu* sıraya koyduğu kriter, gerçek tasarımda doğru olan.

Bu kapı **bilerek kırmızı.** Stage 4, bölümlemesi bilinen tek gerçek tasarımı
henüz bölümleyemiyor, ve paket bunu her koşuda söylüyor. Kırmızı bir kapıyı
açık tutmak, yeşile boyamaktan daha değerli — çünkü neyin eksik olduğunu o
söylüyor.

İki itiraf daha, ikisi de kayıtlı. Birincisi: bu belgenin ilk sürümü `[16]`
cevabını okuyup "demek ki devre tek bir 16-bit akümülatör" diye **yorumlamıştı**.
`00_source.v` iki shift register + toplayıcı + 496 karşılaştırması diyor. Sayı
yanlıştı, isim yanlıştı, ve yorumlamak zaten pipeline'ın işi değildi.
İkincisi: kapı başta sadece **boyutları** karşılaştırıyordu — `[8, 8]` diyen
ama her gruba `sr_a`'dan dört `sr_b`'den dört bit koyan bir cevap "DOĞRU"
geçerdi. Şimdi üyelik de puanlanıyor, ve o hayali cevap tabloda **kalıcı bir
satır**: `interleaved, right sizes — RIGHT SIZES, WRONG MEMBERS, NMI 0.000`.
Kolonun içinde bilinen-kötü bir girdi durmazsa, kolon sessizliktir
(`docs/problems.md` 46).

---

## 4. Puzzle'ın bölümlemesi, ve kalan

Kriterlerin puzzle üzerinde uzlaştığı kadarı dört yazmaç:

```
R0  72 bit   clk, reset (rst_n, düşük)      I'yi ve enable'ı okur
                                            R1 R2 R3'ü besler, O ve success'i sürer
R1  12 bit   clk, reset, n00189'da tutma    I'yi okur, R0'ı besler
R2   4 bit   clk, reset YOK (dfxtp)         R0 ve R3'ü besler, O'yu sürer
R3   4 bit   clk, SET (dfstp, rst_n düşük)  R0'ı besler, O'yu sürer
```

R2 ve R3'ü hatırla: Ders 1'de Stage 1 onları **geometriden** saymıştı — 4
`dfxtp`, 4 `dfstp`. Şimdi aynı sayılar üçüncü bir yoldan, gruplama üzerinden
geri geldi.

**R0 çözülmüş değil.** Tek imza altında 72 bit bir blob; renk arıtma onu 23,
22, 8, 4, 4, 4, 2, 2 ve üç teke kesmek istiyor. Bu kesitler **aday olarak
raporlanıyor ve uygulanmıyor** — çünkü arıtma toplamda daha kötü puan alıyor.

İşte "kalan" (residue) budur: pipeline'ın "buraya kadar" dediği yer. Ders 5'te
söylemiştik — korpus kendi tamlığını kanıtlayamaz, dürüst tek sayı
adlandırılamayanın sayısıdır. R0'ı bir insan okuyacak, elinde dört tamamlayıcı
görüşle: kontrol imzası sınırın *yokluğunu*, akış bölmesi ve arıtma *aday
kesitleri*, bit sırası *zincir yönünü*, yerleşim *fiziksel kümeleri* söylüyor.

---

## 5. Adım 2: tek bir koni, okunur hale getirilmiş

Roadmap'in analiz haftası talimatı: *"success'ten geriye yürü."* Geriye
yürüyünce 738 isimsiz hücre var. `stage4_cone.py` bunu insan okuyacağı bir
listeye çeviriyor: her satır bir hücre, sürdüğü net, ve hücrenin **ne
hesapladığı** — adı değil.

Önce bir olgu: `success` **yazmaçlanmış** bir çıkış. Port doğrudan bir
`dfrtp`'den sürülüyor, yani portun kendi konisi tek sinyal ve hiçbir şey
söylemiyor. İlginç koni o flopun **D girişinin** konisi:

```
47 hücre, 57 sınır sinyali
bağımlılığı:  R0'ın 57 biti — ve başka hiçbir şey
```

Ne birincil giriş var ne sabit. Success koşulu **yalnızca saklanan durumun**
fonksiyonu — Ders 6'da göreceğiz, Stage 6'nın tek SAT çağrısı değil sınırlı
model denetimi olmasının sebebi tam bu.

Listeleme yorum yapmıyor: isim koyuyor (`R0[41]`), liberty fonksiyonlarını
yerine yazıyor, bağımlılık sırasına diziyor. O kadar. "Bunun anlamı ne" sorusu
insanın.

### Listeye neden güvenelim?

İki katman var. Birincisi Ders 5'ten tanıdık: fonksiyon ifadelerini okuyan
parser, PDK'nın kendi davranışsal modellerine karşı 850 tam doğruluk tablosuyla
sınanıyor (`verify_functions.py`) — artı sekiz elle yazılmış tablo, çünkü bu
kütüphane her ifadeyi parantezleyip önceliği hiç test ettirmiyor.

İkincisi bu aşamada eklendi: `verify_cone.py`, warm-up'ın koni listesini
**hiçbir kod paylaşmayan bağımsız bir değerlendiriciyle** okuyor, 65536 girdi
kombinasyonunun hepsinde çalıştırıyor, ve bilinen işlevle karşılaştırıyor:
tam 15 kombinasyon success veriyor (a+b=496'nın çözüm sayısı) ve fonksiyon,
bir bit-ağırlık ataması altında `a + b == 496`'ya **birebir denk.**

Bu kontrol kurulurken, daha sağlam görünen yarıda bir defekt çıktı: ağırlık
çözücüsü ilk bulduğu atamada duruyor ve onu "belirlenmiş" gibi basıyordu.
Oysa 40320 olası atamanın **24'ü** denk — `a + b == 496`, iki işlenen de
256'nın altındayken en anlamlı dört bit çiftini birbirinden hiç ayırt etmez.
Doğru soru "yapısal sıra, 24 denk atamadan biri mi" — tek keyfi üyeyle
karşılaştırmaktan güçlü bir soru (`docs/problems.md` 47).

### Bit sırası: kümeden kelimeye

Stage 4 yazmaçları ilk günden beri **küme** olarak veriyordu. Stage 7'ye kelime
lazım: `O[7:0]`, aynı sekiz flopun başka bir sıralaması değildir. `bit_order`
sırayı yapının verdiği yerde türetiyor:

| Şekil | Kural |
|---|---|
| shift zinciri | öz-kenarları at (Q'su kendi D'sine dönen flop *tutuyordur*, kaymıyordur); kalan graf basit yollara ayrışıyorsa yollar zincirdir, baş önde |
| carry zinciri | graf çevrimsizse ve her bitin en uzun yolu farklıysa, dalga derinliğine göre sırala |
| hiçbiri | **`method: null` ve sebebi.** Düz yazmacın bitleri birbirine bağlı değil — sıralanacak şey yok. LFSR'ın bitleri çevrimsel bağlı — ilk bit yok |

Üçüncü satır bu bölümün asıl cümlesi: **tahmin edilmiş bit sırası, hiç sıra
olmamasından kötüdür** — çünkü Stage 7 o sıradan bir string kuracak.

Warm-up'ta sonuç: tek kontrol imzası altındaki 16 flop, **sekizerlik iki
zincir** olarak çıkıyor — `sr_a` ve `sr_b`. Kontrol imzasının göremediği
sınır, ikinci bir dilde söylenmiş.

Ve iki türetme birbirine karşı sınanıyor: Stage 4 sırayı **tellerden** çıkardı
(D←Q takibi, aritmetikten habersiz); `verify_cone` ağırlıkları
**fonksiyonlardan** çözdü (tellerden habersiz). Bir shift register'da ikisi
birlikte koşmak zorunda: her operand çiftinin iki biti farklı zincirlerde aynı
pozisyonda, ve zincir pozisyonunun imâ ettiği `2^pozisyon` ağırlıkları 24 denk
atamanın arasında. İkisi de tutuyor — ve zincir başının en anlamsız bit olduğu
da buradan çıkıyor: ilk kayan bit, bit 0 oluyor.

(Bir de üçüncü bilinen-kötü girdi: hiç bit sırası taşımayan bir
`registers.json`. İlk sürüm buna "uygulanamaz" deyip **pass içinde**
geçiştiriyordu — yani `bit_order`'daki bir gerileme çapraz kontrolü sessizce
kapatabilirdi. Spec "operandlar seri kayar" diyor; kayan tasarımın sırası
vardır; "sıra türetilemedi" bir atlama sebebi değil bir **başarısızlıktır**.
`docs/problems.md` 48.)

---

## 6. Kendin dene

```bash
python tools/stage4_registers.py --score      # korpus + null modeller + 3 metrik
python tools/stage4_registers.py --compare    # tablo: kriterler yan yana
python tools/verify_blocks.py                 # warm-up'ın kendi cevabı: KIRMIZI
python tools/stage4_cone.py warmup            # koni, okunur halde
python tools/verify_cone.py warmup            # 15/65536 + bit sırası çapraz kontrolü
python tools/stage4_registers.py warmup       # out/warmup/registers.json
```

Üç soru.

1. Warm-up'ın iki yazmacını hiçbir kontrol imzasının ayıramamasının sebebi ne?
   Bu bir implementasyon eksiği mi?
2. `verify_blocks`'a `[8, 8]` boyutlarını tutturan ama üyelikleri karıştıran
   bir cevap ver: eskiden geçerdi, şimdi geçmiyor. Bunu yakalayan satır neden
   **kalıcı** — neden bir kez gösterip silmek yetmez?
3. Birebir eşleşmede birinci olan kriter NMI'da sonuncu. İki metrik de
   "doğruluk" ölçüyor. Çelişki nerede çözülüyor?

### Cevaplar

**1.** İmplementasyon eksiği değil, **bilgi eksiği.** Kontrol imzası yalnızca
kontrol sinyallerini görür; `sr_a` ve `sr_b` saati, reseti ve enable'ı
paylaşır, yani imza uzayında **aynı noktadadırlar.** Aynı noktadaki iki şeyi
hiçbir fonksiyon ayıramaz. Ayrım başka bir uzayda yaşıyor: veri akışında
(bitler karşı yazmaca hiç bağlanmıyor — bağlı bileşenler bunu görür) ve
geometride (iki küme, 21.76 µm arayla — yerleşim bunu görür). Kriterlerin
tamamlayıcı olması tam bu: her biri başka bir uzayda ayrım arıyor.

**2.** Çünkü kolon, içinde duran bilinen-kötü girdi kadar güvenilirdir.
Interleaved satırı silinirse, üyelik karşılaştırmasını bozan bir gerileme
sessizce geri gelebilir ve kolon yine "hep DOĞRU" basar — Ders 5'teki "hiç
yanılamayan kontrol" durumunun aynısı. Satır kalıcı olunca her koşu, kolonun
*hâlâ yanılabildiğini* de gösteriyor. (Aynı desen `--score`'un null modelleri:
her koşuda, skorun yanında.)

**3.** Çelişki yok; iki metrik **iki farklı soru** soruyor. Birebir eşleşme:
"cevabın tamamı, tamamen doğru mu?" — ve korpusun 109 tek-yazmaç netlist'inde
bu soru trivial, tek-grup cevabı bedava doğru. NMI (10 gerçek netlist
üzerinde): "cevabın, gerçeğin sınırları hakkında bilgi taşıyor mu?" Kontrol
imzası trivial olanların hepsini alıp gerçek olanların hiçbirini bölemeyince
birincide şişiyor, ikincide null modele yapışıyor. Çözüm metriklerden birini
seçmek değil: **hangi sorunun senin sorun olduğunu bilmek.** Stage 4'ün sorusu
ikincisi — ve o yüzden üç kolon birden basılıyor.

---

## Sonraki ders

Elimizde artık şunlar var: dört yazmaç, okunur bir success konisi, bit
sıraları, ve dürüstçe işaretlenmiş bir kalan (R0).

Sıradaki soru türü değişiyor. Şimdiye kadar hep "bu **ne**?" diye sorduk.
Ders 6'nın sorusu: **"içine ne yazmalıyım ki success 1 olsun?"**

Bu bir arama problemi, ve elle çözülmeyecek — bir çözücüye (solver)
devredilecek. Ama çözücünün cevabı, modele sorulan sorunun cevabıdır; devreye
sorulanın değil. İkisinin arasındaki farkın nasıl kapatıldığı — ve kendinden
emin, kendi içinde tutarlı, **yanlış** bir çözücü cevabının nasıl yakalandığı —
Ders 6'nın konusu.
