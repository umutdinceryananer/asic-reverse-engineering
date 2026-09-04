# Ders 9 — Puzzle'ı uçtan uca koşmak

Dersler 0-7 pipeline'ı kurdu, Ders 8 onu ölü bir makineden diriltti ve yolda üç
defekt buldu. Bu ders tek bir şeyi anlatıyor: **pipeline puzzle'a doğrultulunca
ne oldu.**

Sonucu baştan söyleyeyim, çünkü bu dersin ilgi çekici kısmı sonuç değil:

```
(* TWO STARS *)
```

İlgi çekici kısım, o cevaba giden yolda **kırmızı yanan bir kapı** ve o kapının
neden yanıldığımızı değil, hangi soruyu sorduğumuzu söylemesi.

---

## 1. Başlangıç noktası: Stage 1-3 ne verdi

Puzzle yolu yeniden koşuldu (Ders 8: `out/puzzle` Mac'le kaybolmuştu) ve
yazarın kayıtlı rakamlarını birebir üretti:

| | |
|---|---|
| Tanımlanan yerleşim | 1618 (728 mantık, 890 fiziksel) |
| Stage 2 instance | 738, 719 iç net, 0 sürücüsüz, 0 çift sürücülü |
| Bağımsız çapraz kontrol | union-find **725/725 hemfikir** |
| Örnek vektörler | 312 cycle, **0 uyuşmazlık** |
| Stage 3 | 92 flop, 16 clock dalı → tek kök, çapraz türetme **723/723** |
| Portlar | giriş `clk`, `rst_n`, `enable`, `I` · çıkış `success`, `O[7:0]` |

`I` **tek bit**. Yani girdi seri.

Bir de doğrulama vardı ki değeri sonradan anlaşıldı: Stage 1, geometrik
tanımlamalarının layout'ta hayatta kalan hiyerarşi isimleriyle uyuştuğunu
söyledi. İki bağımsız kaynak aynı şeyi diyor.

---

## 2. Stage 4 — koni, ve `success`'in neye baktığı

`stage4_cone.py puzzle` tasarımda **189 koni kökü** buldu. İlgilendiğimiz tek
tanesi `success`'i süren flop'un veri girişi:

```
target puzzle, cone root i00228.data
  47 cells, 57 boundary signals

  it depends on
    R0          57  ['R0[0]', 'R0[2]', 'R0[3]', ...]
```

**Elli yedi sınır sinyalinin hepsi R0'ın biti.** Hiçbir birincil giriş bu koniye
ulaşmıyor.

Bu cümle Stage 6'nın neden bounded model checking olduğunu tek başına açıklıyor.
Eğer `success` girişlere doğrudan baksaydı, tek bir SAT sorusu yeterdi: "hangi
girişler bunu 1 yapar?" Ama `success` **saklı duruma** bakıyor, ve o duruma
ancak zaman içinde girişler sürülerek varılıyor. Yani soru "hangi girdi" değil,
"hangi girdi **dizisi**".

---

## 3. Ucuz soru: `--post-reset`

Yayınlanan ipuçlarından biri şunu diyor: *"Don't forget to toggle `rst_n` before
each input attempt."*

Bu ipucu ölçülebilir bir şey söylüyor. `rst_n`'i yeni çevirmiş biri rastgele bir
durumdan başlamıyor: asenkron temizleme taşıyan her flop 0'da, asenkron preset
taşıyan her flop 1'de. Puzzle'da bu **92 flop'un 88'i**. Geriye 4 serbest bit
kalıyor.

Yani `--post-reset` modu 2^92 yerine **2^4 = 16** başlangıç durumu üzerinde
kanıt arıyor. Çok daha ucuz bir soru.

Ve hızlıydı:

```
  total 25.4s over 3 solver calls
  wrote out/puzzle/solution_post_reset.json
```

Derinlik 122'de bir iz. Yirmi beş saniye.

Ama repo'nun kuralı net ve bu dersin bütün konusu o kural: **çözücüden gelen
hiçbir şey, gerçek bir simülatörde tekrar oynatılmadan çözüm değildir.**

---

## 4. Kırmızı kapı

```
cycles replayed  123
mismatches       0
unknown          1
  success is x at cycle 122: the trace does not flush this design's state
RESULT: fail
```

**Uyuşmazlık yok. `x` var.**

Fark önemli. Bir uyuşmazlık, simülasyonun modele "hayır, öyle değil" demesi
demektir — modelde bir kusur var. Bir `x` ise simülasyonun "bilmiyorum" demesi.

### Neden bilmiyor

Simülasyon her flop'u `x`'ten başlatır. Gerçek bir çip de öyle açılır: kimsenin
seçmediği bir durumda. `rst_n` çevrildiğinde asenkron kontrolü olan flop'lar
bilinen bir değere düşer. Olmayanlar düşmez.

Ölçüm:

| | asenkron kontrolü olmayan flop |
|---|---|
| warm-up | **0 / 16** |
| puzzle | **4 / 92** (`i00234`–`i00237`, hepsi `dfxtp_2`) |

`dfxtp_2` sade bir D flip-flop: ne clear'ı var ne preset'i. `--post-reset` tam
olarak o dördünü serbest bırakıyor, ve `x`'ten başlayan bir simülasyonda onları
çözecek hiçbir şey yok. `x` yayılıyor, `success`'in konisine giriyor, ve
`success` sonuna kadar `x` kalıyor.

Yani modun kanıtı **simülasyonun giremediği** 16 başlangıç durumu üzerinde.

Bunu warm-up asla gösteremezdi. Orada 16 flop'un hepsi asenkron reset taşıyor,
bu yüzden warm-up'ta `--post-reset` replay'i **geçiyor** — bu gece de geçti.
Ders 8'in tekrarlayan şekli: *puzzle'ın warm-up'tan geniş olduğu her yer.*

---

## 5. Problem 57 — aynı koşu kendini yalanlıyordu

Kırmızı kapıya bakarken bir şey fark edildi. `replay.py` çıktısının **üst**
tarafında şu not vardı:

> NOTE: this trace was not proven independent of the starting state, so
> simulation from x may legitimately disagree with it.

Ve **yirmi satır aşağıda**, aynı koşu:

> RESULT: fail, the trace does not reproduce. That is a defect in the model
> tools/stage6_invert.py built, not a solution.

İki cümle, tek koşu, tek iz, ve birbirini tutmuyorlar. Üstteki "bu meşru
olabilir" diyor, alttaki "bu bir kusur" diyor.

Sebep: testbench **üç** durumu ayırıyor — uyuşmazlık, `x`, ve temiz geçiş —
ama `mismatches` ve `unknown` için aynı `RESULT: FAIL` satırını basıyordu ve
çağıran taraf sadece o satırı okuyordu. Yani gerçekten bir kusur olan durum ile
zayıf iddianın belgelenmiş davranışı aynı hükmü alıyordu.

Bu, problems.md 49'un bir seviye altta tekrarı: orada durmuş bir Docker on bir
kırmızı kapı gibi okunuyordu, burada zayıf bir iddia bozuk bir model gibi.

Düzeltme, üçüncü bir hüküm:

```
RESULT: unconfirmable, success is x at cycle 122 and no cycle disagrees.
The trace was proven only over this mode's start states, and simulation
begins at x, so this is consistent with the claim that was made. It is not
evidence for it.
```

Çıkış kodu 3. Ve **dar**: koşul `mismatches == 0` gerektiriyor, yani gerçek bir
uyuşmazlık hâlâ `fail` diyor — bağımsız olmayan bir izde bile. İkisi de bozma
testiyle gösterildi.

**Ders: bir kapı "kırmızı" derken hangi soruyu cevapladığını da söylemeli.
"Başarısız" ile "doğrulanamadı" aynı şey değildir, ve ikincisini birincisi diye
raporlamak insanı olmayan bir hatayı aramaya gönderir.**

---

## 6. Güçlü soru, ve `x`'in neden değerli olduğu

Varsayılan mod aynı komuttan `--post-reset` çıkarılarak koşuldu. Bu mod izi
**2^92 başlangıç durumunun tamamı** üzerinde kanıtlıyor.

```
  total 193.6s over 13 solver calls
  wrote out/puzzle/solution.json
```

Derinlik 124. Üç yüz saniye yerine üç dakika — ucuz sorudan sekiz kat pahalı ama
hâlâ küçük.

Ve replay:

```
cycle 124   O=00101000 success=1   model says O=40 success=1
  the property holds: success is 1 at cycle 124

cycles replayed  125
mismatches       0
unknown          0
RESULT: pass
```

Burada bir incelik var ve bu dersin en değerli cümlesi olabilir:

**`x`'ten başlayan bir simülasyon kötümserdir.** Tasarımın sabitlenmemiş her
yerinde `x` yayılır. Yani `x`'ten geçen bir replay, izi **hiçbir başlangıç
durumu söylenmeden** doğrulamış olur. Bu, bir başlangıç durumu varsayıp oradan
geçen bir testten çok daha güçlü bir kanıttır.

Ucuz soru bunu veremiyordu. 168 saniye fazlası tam olarak bunun içindi.

---

## 7. Stage 7 — bus'ı okumak, ve nötr olmayan varsayım

Doğrulanmış iz elde. Şimdi `O[7:0]`'ı okumak:

```bash
python tools/stage7_output.py puzzle --solution out/puzzle/solution.json --extend 64
```

`--extend` gerekli, çünkü iz `success` yükseldiği cycle'da biter — ama çıkış
akışı orada başlar. Uzatmadan bakarsan cevabın ilk baytını görürsün.

Uzatınca ne olacağı ise bir **politika kararı** ve Stage 7 onu gizlemiyor:

| `--after` | ne sürüyor | sonuç |
|---|---|---|
| `hold-last` (varsayılan) | izin son satırı, tekrarlanır | **15 bayt** |
| `zeros` | her giriş sıfır | **1 bayt** |

Neden bu kadar farklı? Çünkü `rst_n` bu tasarımda **aktif düşük**. `zeros`
politikası "sürmeyi bırak" gibi görünüyor ama aslında **reset'i basıyor**.
Çip temizleniyor, akış ikinci bayta varmadan kesiliyor.

**Ders: hiçbir şey sürmemek nötr değildir.** Bir tasarımda "varsayılan" diye
seçtiğin şey, o tasarımın polaritesine göre bir eylemdir. Stage 7 iki satırı da
basıyor, ve yer gerçeği olmayan bir hedefte 15 baytlık okuma ile 1 baytlık okuma
arasındaki farkı bir varsayılanın sessizce seçmesi kabul edilemez.

Sonuç:

```
raw     28 2a 20 54 57 4f 20 53 54 41 52 53 20 2a 29
trimmed cycles 124 .. 138, 15 byte(s)
        '(* TWO STARS *)'
```

Kırpma kontrolü: aralık 138'de bitiyor, son simüle edilen cycle 188. Elli cycle
boşluk var, yani string **tam** — bir önek değil. `O[7]` her baytta 0; hepsi
saf ASCII.

---

## 8. Ne biliyoruz, ne bilmiyoruz

Bu ders bir cevapla bitiyor ama bir açıklamayla bitmiyor, ve aradaki fark
kasıtlı.

**Bildiklerimiz** — hepsi ölçülmüş, hepsi yeniden koşularak denetlenebilir:

- `success` 57 bitlik saklı duruma bakıyor, hepsi R0'ın biti, hiçbir giriş
  doğrudan ulaşmıyor.
- 92 flop'un 79'u yeterli cycle verilirse `success`'e ulaşıyor; **13'ü hiç
  ulaşmıyor.**
- R0'ın aday parçalarından 23, 22 ve 8'lik olanlar koninin **tamamen içinde**;
  üç singleton da içinde; bir 2'lik parça **kesiliyor**. 56 + 1 = 57, koninin
  adlandırdığı sayı.
- Bu, kayda değer: parçalar kontrol imzası ve akıştan türetildi, koni ise
  ikisinden de değil. **Girdisi ortak olmayan iki türetme aynı sınıra iniyor.**
- Kazanan girdi 121 cycle boyunca `enable` yüksekken sürülen seri bit dizisi —
  yayınlanan örnek VCD'nin "her biri 121 bitlik iki deneme" ifadesiyle aynı
  genişlik.

**Bilmediklerimiz:**

- Devrenin ne hesapladığı. R0'ın 72 biti hâlâ çözülmemiş bir blob; altı kriter
  birbirinin ters sıralamasını veriyor.
- `success`'e hiç ulaşmayan 13 flop'un ne yaptığı. (Duyuru bir blok'un çıktı
  üretip başarı koşuluna katılmadığını söylüyor; bu 13'ün o blok olup olmadığı
  **okunmadı**, sadece ölçüldü.)
- Girdinin bir anlamı olup olmadığı.

Bu üçü `out/puzzle/reading-aid.md`'de tablo halinde duruyor — her tablonun bir
**boş `reading` sütunu** var. O sütun kasıtlı olarak boş: doldurulması bir
ölçüm değil, bir okumadır, ve bu depoda okuma yazarın işidir.

---

## Bu dersin bıraktığı

1. **Ucuz soru ile güçlü soru aynı cevabı vermez.** Ucuzu 25 saniyede bir iz
   buldu ve doğrulanamadı; güçlüsü 194 saniyede buldu ve doğrulandı.
2. **`x`'ten geçen bir test kötümserdir, ve bu onu güçlü yapar.** Hiçbir
   başlangıç durumu varsaymadan doğrulamak, bir tane varsayıp doğrulamaktan
   iyidir.
3. **"Başarısız" ile "doğrulanamadı" farklı hükümlerdir.** Aynı hücreye
   koyulduklarında insan yanlış şeyi aramaya gider.
4. **Hiçbir şey sürmemek nötr değildir.** Varsayılanın ne yaptığı, tasarımın
   polaritesine bağlıdır ve basılmalıdır.
5. **Bir cevabı bulmak, onu anlamak değildir.** Bu ders cevapla bitiyor;
   anlamak Ders 10'un işi ve o ders yazarla birlikte yazılacak.
