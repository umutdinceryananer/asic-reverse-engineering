# Ders 8 — Ölü bir makineden pipeline'ı diriltmek

Dersler 0-7 pipeline'ın nasıl kurulduğunu anlatıyor. Bu ders farklı bir şeyi
anlatıyor: **kurulduğu makine öldükten sonra ne oluyor.**

Proje bir Mac'te geliştirildi. O makine emekliye ayrıldı. Geriye tek bir arşiv
commit'i kaldı — *"Archive the whole working tree before the machine is
retired"* — ve üç hafta sonra her şey bir Linux kutusunda yeniden ayağa
kaldırılmak zorunda kaldı.

Bu tatsız bir kaza gibi görünüyor. Aslında projenin en iyi testiydi. Çünkü bir
pipeline'ın "tekrar üretilebilir" olduğunu iddia etmek kolaydır; onu **başka
bir işletim sisteminde, başka bir Python sürümüyle, sıfırdan koşturmak** o
iddiayı sınayan tek şeydir.

Ve sınav sırasında, üç yıl boyunca hiç görülmemiş üç defekt ortaya çıktı.

---

## 1. Önce envanter: ne kurtuldu, ne kaybedildi

Arşiv commit'i `.gitignore`'da olan şeyleri bile zorla eklemişti — `pdk/`,
`.venv`, `out/warmup/`. Bu iyi bir karardı. Ama bir şey eksikti:

```
out/warmup/   35 dosya   KURTULDU
out/puzzle/   —          KAYIP
```

Yazarın puzzle üzerindeki bütün koşu çıktıları — 1618 yerleşim, netlist, graph,
register gruplaması — Mac'le birlikte gitti. Puzzle yolu **sıfırdan yeniden
koşulmak** zorundaydı.

İlk ders burada: **arşivlemek seçici bir iştir ve seçim yanlış yapılabilir.**
`out/warmup` kurtarıldı çünkü bir dizin listesinde gözüktü; `out/puzzle` en
pahalı olanıydı ve kurtarılmadı. Bugün ikisi de commit'li (`eef5a82`).

---

## 2. Docker sorusu, ve yanlış zekice cevap

Pipeline Yosys ve Icarus'u container'dan alıyor, çünkü ikisinin de pip wheel'i
yok. Yeni makinede Docker yoktu ve kurulumu sudo parolası gerektiriyordu.

Yedi araç `docker run`'a gidiyor, satır içi, kaçış yolu olmadan:

```python
subprocess.run(["docker", "run", "--rm", "-v", f"{os.path.abspath('.')}:/work",
                "-w", "/work", IMAGE, "yosys", "-p", script])
```

Makinede ise OSS CAD Suite kuruluydu — Yosys 0.68, Icarus 14.0, z3, hepsi
yerli. İki seçenek göründü:

**A.** PATH'e `docker` adında sahte bir script koy, argümanları soyup gerisini
yerinde çalıştır. Repo'da sıfır değişiklik, beş dakika.

**B.** Yedi çağrı yerini düzenle, container ya da yerli prefix döndüren bir
yardımcıya bağla.

İlk içgüdü B'ydi: "shim hile gibi, düzgün düzeltelim." Bu **yanlıştı**, ve
nedenini repo'nun kendisi söylüyor. `review_packet.py:487` bir aracın container
gerektirip gerektirmediğini **kaynağında `docker` kelimesi geçiyor mu** diye
türetiyor. O literal'i silseydik paket *"bir container satırı beyan etti ama
kaynağı docker'dan hiç bahsetmiyor"* deyip yazmayı reddederdi — bu, problems.md
53'te bir kez yaşanmış bir defekt.

Ama asıl cevap üçüncüydü ve ikisinden de basitti: **`docker.io` Ubuntu noble'ın
kendi deposunda var.** Linux Mint 22.3 onu takip ediyor. Tek komut:

```bash
sudo apt install -y docker.io
```

Ve bu, sadece kolay olduğu için değil, **doğru** olduğu için tercih edildi.
Container'lar `debian:bookworm-slim`'i digest'le pinliyor ve içindeki
sürümleri bir manifest'e yazıyor. `verify_toolchain.py` o manifest'i
`tools/TOOL_VERSIONS.recorded` ile satır satır karşılaştırıyor:

```
iverilog  Icarus Verilog version 11.0 (stable) ()
yosys     Yosys 0.23 (git sha1 7ce5011c24b)
z3        Z3 version 4.8.12 - 64 bit
```

Container kurulunca bu satırlar **birebir tuttu.** Yerli OSS CAD Suite ile
gitseydik Yosys 0.68 ve Icarus 14.0 olurdu, kapı DRIFT'ten kırmızı yanardı, ve
onu yeşile boyamanın tek yolu kaydı yeniden yazmaktı — ki problems.md 36 bunu
açıkça yasaklıyor: *yeniden kayıt bir karardır, yan etki değil.*

**Ders: en zekice çözüm en iyi çözüm değildir. Doğru soru "bunu nasıl
atlatırım" değil, "bu kısıt neyi koruyordu" idi.** Kısıt, ölçümlerin altındaki
sürüm öncülünü koruyordu.

---

## 3. Bayt-aynılık: iddianın sınandığı yer

Toolchain ayağa kalkınca warm-up yolu baştan koşuldu ve her çıktı arşivdekiyle
karşılaştırıldı. macOS + Python 3.14'te üretilenler ile Linux + Python 3.12'de
üretilenler:

| Bayt bayt aynı | Farklı |
|---|---|
| `instances.json`, `netlist.v`, `netlist_unionfind.json`, `graph.json`, `graph.v`, `cone.json`, `registers.json`, `output.json`, `yosys.json`, `celllib.v`, `blackbox.v`, `equiv.ys`, `tb_output.v` | `netlist.json`, `solution.json`, `bmc_k*.smt2` |

Yani **çıkarım omurgasının tamamı iki işletim sisteminde birebir aynı.** Bu,
"deterministik pipeline" iddiasının en güçlü kanıtı ve kimse onu böyle test
etmeyi planlamamıştı.

Farklı olan üçü de zararsız çıktı, ama üçüncüsü bir defekt gizliyordu:

**`netlist.json`** — sadece isimsiz net adları (`$88` ↔ `$87`). Stage 2 Verilog'a
giderken yeniden numaralandırdığı için (problems.md 32) `netlist.v` **aynı**, ve
aşağıdaki her şey aynı. Alınacak ders: **hiçbir şey `$`-adlara anahtar
bağlamamalı.** Bunlar tanımlayıcı değil, dolgu.

**`solution.json`** — yalnızca `seconds` ve `total_seconds`. İz birebir aynı.

**`bmc_k*.smt2`** — ve bu, bir sonraki bölümün konusu.

---

## 4. Problem 54 — aynı gerçeğin iki kez kaydedilmesi

Stage 6 puzzle'da ilk kez koşturulunca çözmeden çıktı:

```
net n104 is driven by more than one thing: ('const', 0) and i07290.LO
```

`i07290` bir `conb_1` — bir **tie hücresi**. İşi tek bir şey yapmak: çıkışını
sabit tutmak. `LO` pini hep 0, `HI` pini hep 1.

Stage 3 bunu görüyor ve `constant_nets`'e yazıyor, çünkü bir sabit **cone
sınırıdır**: koni yürüyüşü orada durur, tıpkı bir flop çıkışında veya birincil
girişte durduğu gibi. Sonra Stage 6 aynı hücreyi *fonksiyonu olan bir hücre*
olarak da görüyor ve "bu neti iki şey sürüyor" diyor.

İkisi de doğru. İkisi de **aynı şey.**

### Warm-up bunu neden gösteremezdi

```
warm-up  constant_nets: 0
puzzle   constant_nets: 12   (6 conb_1 × 2 pin)
```

Warm-up'ta hiç tie hücresi yok. Bu kod yolu orada **tetiklenemezdi.** docs/06'nın
kendi cümlesi de bunu söylüyor: *"Nothing here has run on the puzzle."*

Bu, problems.md 52'nin şekli: **puzzle'ın warm-up'tan geniş olduğu her yer, bir
varsayımın bütün projeyi atlatabileceği bir yerdir.**

### Ve neden kolay düzeltme yanlıştı

En kısa yama şu:

```python
if net in constant_nets:
    continue        # sabitse atla
```

Üç kelime daha kısa ve **yanlış.** Çünkü Stage 1, o altı `conb_1`'i tam
geometrik parmak iziyle değil, **yapısal geri düşüş** katmanıyla tanımıştı —
çekilen PDK sürümü puzzle'ı çizen sürüm değil. Körü körüne atlamak, yanlış
tanınmış bir tie hücresini tam olarak yutacak şeydi.

Onun yerine atlama **koşullu**: hücrenin kendi fonksiyon ağacı kayıtlı sabite
eşitse atla, değilse sert dur.

```python
recorded = constants.get(net)
if recorded is not None:
    if tree.kind == "const" and int(tree.value) == int(recorded):
        skipped += 1
        continue
    sys.exit(f"net {net}: recorded constant {recorded} but driven by "
             f"{instance}.{pin}, whose function is not that constant")
```

İki taraftaki `int()` süs değil: stage 3 liberty fonksiyonundan **int**, `const:`
literalinden **string** yazıyor (`stage3_graph.py:462` ve `:465`).

**Sonradan gelen teyit:** aynı Stage 1, alternatif kütüphaneye karşı da
koşuldu — `--library pdk/open_pdks_sky130A`. Sonuç: **exact 1618, structural 0.**
Yirmi iki geri düşüşün hepsi, altı `conb_1` dahil, tam eşleşmeye çıktı. Yani
endişe yersizdi *ve bunu ölçerek öğrendik*, varsayarak değil.

---

## 5. Problem 55 — belirtisi olmayan defekt

54'ün yamasını yazarken bir şey fark edildi. Aynı fonksiyonda, on satır
yukarıda:

```python
produced[wires[0]] = (instance, pin, functions[(cell["type"], pin)])
```

Düz bir atama. Aynı neti **iki hücre** sürerse, ikincisi birincisini sessizce
eziyor ve geriye hiçbir iz kalmıyor. Aşağıdaki çift-sürücü kontrolü
`self.driver`'a bakıyor, o ise ezmeden sonra tek sürücü görüyor. Yani o kontrol
hücre-vs-sabit, hücre-vs-giriş, hücre-vs-flop çakışmalarını görüyordu ama
**hücre-vs-hücre çakışmasını hiç göremiyordu.** Hangisinin hayatta kalacağı,
sıralanmış instance adına bağlıydı.

Maliyeti ölçüldü. Warm-up'ın graph'ına iki hücre aynı nete bağlandı ve
düzeltme öncesi kod koşuldu:

- **Bir clock ağacı netinde:** *"38 net(s) read and undriven ... the transition
  relation is incomplete"*, çıkış 2. Doğru bir cümle, ama aşağı akıştaki bir
  belirti hakkında; kusurun yanından geçmiyor.
- **Bir veri yolu netinde:** `RESULT: pass, a trace was found`, çıkış **0**.

Yani var olmayan bir tasarımı çözüp cevap diye veriyordu.

### Nasıl bulundu — ve nasıl bulunmadı

İlk yazılan çerçeve şuydu: "54, 55'i maskeliyordu." Bu **mekanik olarak
yanlıştı** ve denetimde düzeltildi. `produced` kurulum döngüsü, 54'ün çıkışının
yaşadığı sürücü döngüsünden **önce** biter; yani hücre-hücre körlüğü tie
hücresi olsun olmasın her yolda tamdı. Maliyet ölçümü zaten warm-up'ta koştu,
orada tie hücresi yok.

Doğrusu şu: **54'ü denetlemek 55'i buldu.** Tek bir invariant'ın — *net başına
tek sürücü* — on satırında, her doğru `conb_1`'de çalan bir alarm ile hiç
çalamayan bir kontrol yan yana duruyordu. Birincisine yakından bakmak
ikincisini görünür kıldı.

**Taşınabilir ders: gürültülü bir kontrolün baktığı şey hakkında yanıldığını
anladığında, sessiz kalan yarıya inanmadan önce aynı invariant'ın öbür yarısını
oku.**

---

## 6. Problem 56 — dosya adı bir iddiadır

`bmc_k*.smt2` farkı Mac ile Linux arasında bir çözücü farkı gibi görünüyordu.
Değildi.

Stage 6'nın iki modu var. Varsayılan mod izi *her* başlangıç durumu üzerinde
kanıtlar; `--post-reset` sadece `rst_n` çevrildikten sonraki durumlar üzerinde.
docs/06 hangisinin daha güçlü olduğunu açıkça söylüyor ve şunu ekliyor: **zayıf
iddia güçlü olanın yerini sessizce almamalı.**

Çözüm dosyaları bu kurala uyuyordu — `solution.json` ve `solution_post_reset.json`
ayrı. **Sorgu dosyaları uymuyordu:** ikisi de `bmc_k{k}.smt2` yazıyordu. Yani
diskteki dosya hangi soruyu cevapladığını söylemiyordu, ve `review_packet` iki
modu da koşturduğu için her pakette biri diğerini eziyordu.

Arşivdekilerde `q0_` ve `q1_` prefiksleri vardı (iki kopya = varsayılan mod,
karşı-örnek durumunu ikinci kopya olarak pinliyor), yenilerinde sadece `q0_`.
Ölçüm bunu kesinleştirdi: temiz ağaçtan yalnız varsayılan koşu dokuz dosyanın
hepsini arşivle bayt bayt aynı bırakıyor.

Düzeltme bir parametre: `search(..., suffix="_post_reset" if post_reset else "")`.

**Ders: bir artefaktın adı, o artefaktın hangi soruyu cevapladığına dair bir
iddiadır. İki farklı soru aynı adı paylaşıyorsa, ikisi de yalan söylüyor.**

---

## 7. Bir gösterim program olmalı

54 ve 55 elle gösterildi: bozuk graph'lar üretildi, transcript'ler alındı,
"işte yakalıyor" denildi. Bu, projenin kendi kuralına aykırıydı — problems.md
26-28'in tam olarak eleştirdiği şey: *elle bir kez yapılıp düzyazıya yazılmış
bir ölçüm, bir kez olmuş bir ölçümdür.*

Bu yüzden `stage6_invert.py --selftest` yazıldı. Bellekte kurulan dört sentetik
graph, container yok, çözücü yok, korpus yok:

```
  a tie cell that agrees             built, 1 skipped
  the recorded constant flipped      caught: net nlo: recorded constant 1 ...
  a second cell on that net          caught: net nlo is driven by two cells ...
  a literal constant, no producer    built, 1 skipped of 2 recorded

RESULT: pass, 4 of 4 cases behaved as specified
```

Dördüncü vaka bozma değil. Üreticisi olmayan bir `const:` netinin `skipped` ile
`recorded` sayılarını **meşru olarak** ayırdığı durum — kayda geçirildi ki
sonradan biri o eşitsizliği defekt sanmasın.

Ve selftest'in kendisi de sınandı: 54'ün koruması gevşetildiğinde yalnız
"flipped constant" kırmızıya dönüyor, 55'inki silindiğinde yalnız "second cell".
Her vaka kendi koruması için konuşuyor.

---

## 8. Dürüstlük paragrafı — bölüşüm bu turda değişti

Önceki yedi ders, README'nin ilan ettiği bir çalışma bölüşümü altında yazıldı:

> Asistan aşamaları ve kapıları inşa eder, `warmup` ve `synth` üzerinde
> doğrular. **Yazar** pipeline'ı `puzzle` üzerinde koşar, blok bölünmesini
> yorumlar, devrenin ne hesapladığını belirler, kazanan girdiyi türetir ve
> writeup'ı yazar.

Bu, yarışmanın yayınlanan kuralından **daha sıkı** bir bölüşümdü ve kasıtlıydı.

**Bu turda o sınır kaldırıldı.** Deposu sahibi, teslim tarihi geçtikten sonra,
puzzle koşularının ve mekanik analizin de asistan tarafından yapılmasını
istedi — öğrenme amacıyla, ve bu ders notlarının üretilmesi şartıyla.

Ne değişti, ne değişmedi:

- **Değişti:** puzzle üzerinde `stage4_cone`, `stage6`, `replay`, `stage7`
  koşuldu; `reading_aid.py` yazıldı.
- **Değişmedi:** hiçbir dil modeli pipeline'ın *içinde* koşmuyor. Bir dedektör
  hâlâ bir algoritma, bir prompt değil.
- **Değişmedi:** "bu devre X hesaplıyor" cümlesi kurulmadı. `reading-aid.md`
  her tablosunda boş bir `reading` sütunu taşıyor.
- **Değişmedi:** `docs/writeup.md` yazarındır ve asistan yazmaz.

Bu paragraf burada duruyor çünkü **bir metodolojinin ne zaman ve neden
gevşetildiği, metodolojinin kendisi kadar önemlidir.** Bir okuyucu bu depoyu
değerlendirirken hangi sonucun hangi kural altında üretildiğini bilmeli.

---

## Bu dersin bıraktığı

1. **Tekrar üretilebilirlik iddiası ancak başka bir makinede sınanır.** Bu proje
   sınandı ve çıkarım omurgası iki işletim sisteminde bayt bayt aynı çıktı.
2. **Bir kısıtı atlatmadan önce onun neyi koruduğunu sor.** Docker'ı taklit
   etmek beş dakikaydı; kurmak, ölçümlerin altındaki sürüm öncülünü korudu.
3. **Warm-up'ın gösteremediği her şey, gösterilmemiş demektir.** 0 tie hücresi,
   0 asenkron kontrolsüz flop — ikisi de puzzle'da defekt üretti.
4. **Gürültülü bir kontrolü düzeltirken aynı invariant'ın sessiz yarısını oku.**
5. **Bir gösterim program değilse, bir kez olmuştur.**

Ders 9, bu düzeltmelerin ardından puzzle'ın uçtan uca koşulmasını anlatıyor —
ve orada kırmızı yanan bir kapının neden dersin en öğretici sahnesi olduğunu.
