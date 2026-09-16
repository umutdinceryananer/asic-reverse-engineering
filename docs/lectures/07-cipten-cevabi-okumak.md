# Ders 7 — Çipten cevabı okumak

Ders 6'nın sonunda elimizde `success`'i yükselten girdi dizisi vardı, ve ona
güvenmemizi sağlayan bir kapı. Zincirin son halkası bu ders — çünkü yarışmanın
istediği şey bir girdi dizisi değil:

> *"The string value you recovered from the chip"* — çipten kurtardığın
> **metin**.

Duyuru nasıl alınacağını da söylüyor: çıktı üreteci *"ilk tersine mühendislik
adımlarında görmezden gelmek güvenli, ama nihai cevabı almak için simüle etmen
gerekecek."*

Yani Stage 7 yeni bir çözücü değil. **Zaten var olan simülasyona farklı bir
soru sormak:** trace'i netlist'ten geçir, ve `O[7:0]` çıkış bus'ını çevrim
çevrim oku. Bayt bayt. Sonra baytları karaktere çevir.

Kulağa on satırlık iş gibi geliyor. Bu ders, neden olmadığını anlatıyor — ve
yol üstünde, bu projenin en sinsi defektlerinden birinin nasıl yakalandığını.

---

## 1. Tek sürücü, iki araç

Ders 6'dan `sim/replay.py`'yi hatırla: trace'i **Stage 2'nin** netlist'inden,
PDK'nın kendi hücre modelleri altında, Icarus'ta geçiriyordu. Stage 7 aynı
simülasyonu istiyor, sorusu farklı.

İlk karar bu yüzden mimari: iki araç **aynı sürücüyü** paylaşmalı. Bir çevrimin
zamanda nasıl yerleştiği ("girişler saat düşükken değişir → otur → örnekle →
yükselen kenar") ve hücre modellerinin Icarus'a nasıl verildiği — bunlar
`sim/harness.py`'ye taşındı ve iki araç da onu çağırıyor.

Neden? Çünkü iki ayrı sürücü, aynı inceliği **iki ayrı yerde yanlış yapma**
fırsatı demek. VCD zamanlaması bu projede bir kez tuzak oldu (Ders 2'nin
sıfır-gecikme dökümü); o kuralın tek bir yerde yazılı olması, iki kopyasının
sessizce ayrışmasından iyidir.

Ve ikinci tüketiciyi yazmak, **birincinin varsayımını görünür kıldı.**

---

## 2. Problem 52: warm-up'ın itiraz edemediği varsayım

`replay.py` her çıkış portu için testbench'e şunu yazıyordu:

```verilog
wire S;
```

Tek telli bir `wire`. Warm-up'ın tek çıkışı `S` ve gerçekten tek bit — yani
varsayım ile gerçek uyuşuyordu, ve kapı 65536 kez geçti.

Şimdi puzzle'ı düşün: `O[7:0]`, sekiz bit. `wire O;` yazıp `.O(O)` bağlamak,
**bit 0'ı bağlayıp yedi biti boşta bırakmak** demek. Yazarın kendi puzzle
replay'i, çıkış bus'ının sekizde yedisinde `x` okuyacaktı — pipeline'ın **son
adımında** — ve hiçbir kapı bunu yakalayamazdı, çünkü hiçbir kapı puzzle'da
koşmuyor.

Nasıl yakalandı? İnceleme ile değil, bir kontrol ile de değil. Stage 7'nin
aracı bir **bus** okumak zorundaydı, bus için genişlik lazımdı, genişliği
netlist'in kendi beyanından okudu (`harness.port_widths`) — ve o an birinci
aracın varsayımı göründü. İkisi de artık genişlikleri aynı yerden alıyor.

> Bu dersin metodoloji cümlesi: **bir varsayım, ancak ona itiraz edebilecek
> bir girdiyle karşılaşınca görünür olur.** Warm-up'ın bus'ı yok — yani
> "her port tek bit" varsayımına warm-up *itiraz edemezdi.* Kapının 65536 kez
> geçmesi varsayımı doğrulamıyordu; sadece sınamıyordu. Ders 5'teki "hiç
> yanılamayan kontrol" hikâyesinin bir başka yüzü: buradaki kontrol
> yanılabiliyordu ama *bu konuda* yanılamazdı.

`docs/problems.md` 52. Sinsiliği şurada: defekt canlıydı, senin puzzle
koşunun yolunun üstündeydi, ve onu ancak **ikinci bir tüketici yazmak**
çıkardı.

---

## 3. İki düğme, ve neden ikisi de çıktıya yazılıyor

Trace, özelliğin tuttuğu çevrimde bitiyor. Ama bir string'in o çevrimde
bitmiş olması — ya da başlamış olması — için hiçbir sebep yok. Bayt bayt akan
bir metnin uzunluğunu pipeline'daki hiçbir şey bilmiyor.

İki düğme bu yüzden var, ve ikisi de **türetilemez** — o yüzden ikisi de
(varsayılanlar dahil) her sonuçla birlikte basılıyor ve `output.json`'a
yazılıyor:

**`--extend N`** — trace bittikten sonra N çevrim daha saat at. Tablo, hangi
çevrimlerin trace hangilerinin uzatma olduğunu işaretliyor.

**`--after <politika>`** — trace bitince girişleri kim sürecek?

| Politika | Uzatma çevrimlerinde girişler |
|---|---|
| `hold-last` *(varsayılan)* | trace'in son satırı, tekrarlanır |
| `zeros` | her giriş düşük |
| `port=değer,...` | son satır, adı geçen portlar değiştirilmiş |

Bunun kozmetik olmadığı **ölçüldü**: aynı warm-up trace'i, dört çevrim, üç
politika — 8. çevrimden sonra üç farklı cevap:

| `--after` | S, 9..12. çevrimlerde |
|---|---|
| `hold-last` | `1 1 1 1` |
| `zeros` | `0 0 0 0` — çünkü `rst_n` aktif-düşük, sıfırlamak reseti çekmek demek |
| `en=1,A=1` | `1 0 0 0` — kaydırma sürüyor, toplam 496'dan uzaklaşıyor |

`hold-last` neden varsayılan? Trace'in son satırı, özelliğin tutmasıyla tutarlı
olduğu **bilinen** tek giriş ataması. Bu bir akla-yatkınlık argümanı, türetme
değil — ve tam bu yüzden politika sonuca *yazılıyor*, sessizce uygulanmıyor.
**Kendini gizleyen bir varsayılan, sonuç kılığında bir tahmindir.**

---

## 4. Warm-up'ta `NONE` doğru cevaptır

```
$ python tools/stage7_output.py warmup --extend 4
  stream     NONE   (this design has no multi-bit output port)
```

Warm-up'ın tek çıkışı `S`, tek bit. Okunacak bus yok — ve araç bunu bir hata
olarak değil, **olgu** olarak söylüyor.

İnce ama önemli bir tasarım kararı: akış portu `O` **adıyla** değil,
**netlist'teki genişliğiyle** seçiliyor (en geniş çıkış). Çünkü "`O`" puzzle'a
ait bir olgu, ve bu araç `O`'su olmayan hedeflerde de çalışmak zorunda — az
önce çalıştı da. Genişlikte eşitlik olursa araç tahmin etmiyor, `--port`
istiyor.

Yani warm-up, Stage 7'nin her parçasını sınıyor — replay, uzatma, politika,
tablo, `output.json` — **çözümleme hariç.** Çözümlemenin kapısı başka yerde
olmak zorundaydı.

---

## 5. Kapı: simülasyondan önce yazılmış string'ler

Puzzle'da Stage 7'nin okuduğunu kontrol etmenin yolu yok — olsaydı puzzle
çözülmüş olurdu. Ders 5'in ilkesi son bir kez: kontrol, cevabın **önceden
yazılı olduğu** yerde yapılır. Korpusa bir `streamer` ailesi eklendi: tek
çevrimlik bir tetikten sonra, beyan edilmiş bir ASCII string'i çevrim başına
bir bayt yayınlayan, sonra susan devreler.

| Devre | String | Bayt |
|---|---|---|
| `streamer_hello` | `HELLO WORLD` | 11 |
| `streamer_escape` | `OK\a 42\n` | 7 |

Neden iki tane? Uzunluğu içine gömmüş bir çözücü, tek örnekte geçerdi. Neden
biri yazdırılamayan baytlı? Çünkü kaçış yolu (`\a`, `\n`), sadece
yazdırılabilir string'in **hiç sınamayacağı** kısım.

Karşılaştırılan dört şey var, ve ikincisiyle üçüncüsü işin özü:

1. **Baytlar, eleman eleman** — beyanla. Metni metinle karşılaştırmak değil;
   o, çözücüyü kendisiyle karşılaştırmak olurdu.
2. **Akışın yeri.** İlk boş-olmayan bayttan sonuncusuna. Doğru baytları yanlış
   çevrimlerde üreten bir akış birinciyi geçer, bunu geçemez.
3. **Çevirim geri-dönüşü.** `verify_output.unescape`, hiçbir kod paylaşmayan
   ikinci bir küçük implementasyon: çevrilmiş metni baytlara **geri** çeviriyor.
   Kontrol baytını olduğu gibi geçiren bir çevirici, string'e *benzeyen* ama
   geri okunamayan metin üretir — burada yakalanır. "Bayt düşürülmedi" bir
   iddia değil, kapının test ettiği bir özellik.
4. **Meşgul bayrağı**, beyan edilen çevrimlere karşı.

Ve her streamer'ın **her iki eşlemesi** geçmek zorunda — Ders 5'in kuralı:
tek bir `abc` koşusunda hayatta kalan bir akış, o koşunun özelliğiydi.

```
$ python tools/verify_output.py
  ok  streamer_hello[base]   11 bytes at cycles 3..13   'HELLO WORLD'
  ok  streamer_hello[fast]   11 bytes at cycles 3..13   'HELLO WORLD'
  ok  streamer_escape[base]   7 bytes at cycles 3..9    'OK\a 42\n'
  ok  streamer_escape[fast]   7 bytes at cycles 3..9    'OK\a 42\n'
RESULT: pass

$ python tools/verify_output.py --selftest
  caught  çözülmüş akışın bir baytı değiştirildi
  caught  beyan edilen string'in bir karakteri değiştirildi
  caught  çevirimde ham bir kontrol baytı bırakıldı
  3/3 caught
```

Bir ayrıntı daha, cevap anahtarı disiplininden: beyan edilen çevrim numaraları
ve canlı bit sayısı, koşudan **geri okunmuyor** — üretici bunları kendi
argümanlarından, Yosys koşmadan önce hesaplıyor. (Güzel bir yan olgu: ASCII'de
her baytın 7. biti sıfır, yani çıkış yazmacının o biti sabit — `opt` onu
söküyor ve `O[7]` bir `conb_1`'den geliyor. Stage 3 yedi flop buluyor, beyan
yedi diyor.)

---

## 6. Yan etki: matris kımıldadı

Streamer'lar korpusa dört netlist ekledi, ve Ders 4'ün NMI kolonu **yeniden
sıralandı**: bağlı bileşenler tepeyi kaybetti, çünkü streamer'lar renk
arıtmanın tam isabetli, bileşenlerin tam isabetsiz olduğu ilk devreler.

Dört netlist bir sıralamayı değiştirebiliyorsa, o sıralama örnekleme
duyarlıdır. Ders 4'ün dersi burada keskinleşiyor: **kriter kararı tek bir
kolona dayanamaz.** Warm-up'ın gerçek cevabı, tamamlayıcı-görüşler çerçevesi
ve kalan raporu — karar oradan çıkar, korpus sıralamasından değil.

---

## 7. Yazarın koşusu, ve Stage 7'nin yapmadığı şey

Stage 6 bir çözüm yazdıktan sonra Stage 7'nin tamamı tek satır:

```
python tools/stage7_output.py puzzle --extend 64
```

Bakılacaklar, sırayla: `stream` satırı `O` demeli (`NONE` diyorsa sorun burada
değil, yukarıda) → success çevrimi tabloyla uyuşmalı (önce replay!) → akış
success'ten önce mi başlıyor sonra mı (ikisi de mümkün, farklı şeyler anlatır)
→ son boş-olmayan bayt son simüle çevrimse akış **kesilmiştir**, `--extend`'i
büyüt → `hold-last` ile `zeros` aynı cevabı veriyor mu (vermiyorsa o fark
writeup malzemesi) → çıktıda `\?` görürsen o bir bayt değil, simülasyonun
`x`/`z` bıraktığı bir çevrimdir.

Ve son çizgi: **Stage 7 string'i asla yorumlamaz.** Bus'ın taşıdığı baytları
raporlar, yazdırılamayanı kaçışla gösterir. Hangi baytların cevap olduğu ve
cevabın ne *anlama geldiği* — `CLAUDE.md`'nin iş bölümünde çizginin öbür
tarafı. Bu araç, o çizgiden önceki son araçtır.

---

## 8. Kendin dene

```bash
python tools/stage7_output.py warmup --extend 4              # NONE, ve neden
python tools/stage7_output.py warmup --extend 4 --after zeros
python tools/verify_output.py                                # kapı
python tools/verify_output.py --selftest                     # 3/3
```

Üç soru.

1. Warm-up'ta `stream NONE` bir başarısızlık mı? Aracın burada "en geniş
   çıkış `S`'dir, onu akış sayayım" dememesi neden doğru?
2. Kapı neden çevrilmiş metni beyan edilen metinle karşılaştırmıyor da
   baytları karşılaştırıp çevirimi ayrıca geri-dönüşle sınıyor?
3. Problem 52'yi hiçbir kapı yakalayamazdı, dedik. Peki onu ne yakaladı, ve
   bundan hangi genel kural çıkar?

### Cevaplar

**1.** Başarısızlık değil, olgu. Tek bitlik `S`'yi "akış" saymak, olmayan bir
cevabı üretmek olurdu — ve Ders 4'ün bit-sırası kuralının aynısı geçerli:
**tahmin edilmiş bir çıktı, hiç çıktı olmamasından kötüdür**, çünkü üstüne
string kurulur. Araç genişliğe bakıyor, bir bus bulamayınca bulamadığını
söylüyor. "Cevap veremiyorum" demek, burada doğru cevap.

**2.** Çünkü metin-metine karşılaştırma, çözücünün hatasını **iki tarafta
birden** taşır. Kontrol baytını ham geçiren bir çevirici düşün: çevrilmiş
metin beyanın çevrilmişine benzeyebilir, ve karşılaştırma kendi hatasıyla
uzlaşır. Baytlar ham gerçek; çeviri ayrı bir katman; ikisini ayrı sınamak
gerekiyor. `unescape`'in **ikinci, kod paylaşmayan** bir implementasyon olması
Ders 3'ten beri gördüğümüz desen: aynı belgeyi iki kez okumak doğrulama
değildir.

**3.** Onu, aynı altyapıya yazılan **ikinci tüketici** yakaladı: yeni araç
genişliklere muhtaçtı ve onları netlist'ten okuyunca eski aracın "her port tek
bit" varsayımı çelişkiye düştü. Genel kural: bir varsayımın sınanması için ona
itiraz edebilecek bir girdi ya da tüketici gerekir; yoksa geçen her test
sessizliktir. Pratik hali — kritik bir altyapının ikinci bir tüketicisini
yazmak, o altyapının en ucuz denetimidir.

---

## Serinin sonu

Ders 0'da elimizde ne vardı, hatırla: **on binlerce dikdörtgen.** Şeması yok,
kodu yok, isimleri silinmiş.

Zincir şimdi tam:

```
dikdörtgenler → hücreler (1) → teller (2) → etiketli graf (3)
→ yazmaçlar ve koniler (4) → cevabı bilinen korpus (5)
→ girdi dizisi (6) → string (7)
```

Ve her halkanın altında bir kapı: DEF karşılaştırması, iki bağımsız çıkarıcı,
simülasyon, çapraz kontrol, denklik kanıtı, replay, streamer'lar. Otuz dokuz
kapı, bir rapor — ve bir tane **bilerek kırmızı** duran kapı: `verify_blocks`,
Stage 4'ün, bölümlemesi bilinen tek gerçek tasarımı henüz bölümleyemediğini
her koşuda söylüyor.

Pipeline'ın işi burada bitiyor. R0'ın 72 bitini okumak, devrenin ne
hesapladığını söylemek, kazanan girdinin anlamını çıkarmak ve writeup'ı yazmak
— bunlar bilerek ve kural gereği bir insanın işi. Dikişin yeri tam burası, ve
bu projenin en ilginç gözlemi de muhtemelen dikişin kendisi: **bir makinenin
nereye kadar götürebildiği, ve bir insanın nereden devralması gerektiği.**
