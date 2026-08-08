# Työpaikkatutka

Versio 1.6.3

Windowsilla toimiva työnhakuvahti. Ohjelma tarkistaa valitut työnantajien
urasivut, etsii käyttäjän profiiliin sopivia paikkoja, pisteyttää tulokset
ja pitää kirjaa jo käsitellyistä ilmoituksista.

Ohjelma ei lähetä työhakemusta työnantajalle ilman käyttäjän omaa päätöstä.
Hakuilmoituksen saa avattua ohjelmasta, minkä jälkeen hakemuksen voi tehdä ja
lähettää työnantajan sivulla.

## Nopea käyttöönotto Windowsissa

1. Pura ZIP-tiedosto omaan kansioon.
2. Asenna [Python 3.11 tai uudempi](https://www.python.org/downloads/windows/).
   Valitse asennuksessa **Add Python to PATH**.
3. Kaksoisnapsauta `ASENNA.bat`. Asennus luo työpöydälle
   **Työpaikkatutka**-pikakuvakkeen.
4. `ASENNA.bat` luo tarvittaessa `config.json`-tiedoston.
5. Käynnistä ohjelma tiedostosta `KAYNNISTA.bat`.
6. Avaa **Avaa asetukset**, tarkista hakuprofiili ja tallenna.
7. Paina **Etsi työpaikkoja**.

Erillisiä Python-kirjastoja ei tarvitse asentaa. Ohjelma käyttää vain Pythonin
mukana tulevia osia.

## Ensimmäinen julkinen julkaisu

Versio **1.6.1** on Työpaikkatutkan ensimmäinen julkisesti saatavilla oleva
versio. Aiemmat versionumerot olivat vain sisäisiä kehitysversioita, eikä niistä
ole julkaistu ladattavia paketteja.

Julkaisupaketti ei sisällä käyttäjän `config.json`-tiedostoa eikä
`data/jobs.db`-tietokantaa. Ne luodaan paikallisesti ohjelman käytön aikana,
eikä niitä pidä lisätä GitHub-repositoryyn.

## Mitä käyttöliittymän painikkeet tekevät?

- **Etsi työpaikkoja:** tarkistaa kaikki käytössä olevat lähteet.
- **Avaa ilmoitus:** avaa valitun työnantajan hakuilmoituksen selaimessa.
- **Lähdelinkit:** näyttää kaikki osoitteet, joista sama ilmoitus löytyi.
- **Merkitse haetuksi:** tallentaa, että hakemus on lähetetty.
- **Haetut työpaikat:** avaa hakuhistorian, jossa näkyvät työnantaja,
  työtehtävä ja hakupäivä. Ilmoituksen voi avata kaksoisnapsauttamalla riviä.
- **Poista listasta:** piilottaa paikan tavallisesta näkymästä pysyvästi.
  Poistetut saa tarvittaessa näkyviin valinnalla **Näytä poistetut**.
- **Avaa asetukset:** avaa samaa vaaleaa tai tummaa teemaa käyttävän graafisen
  asetussivun. Asetuksia ei tarvitse muokata JSON-koodina.

Vihreä tulos sopii profiiliin hyvin, keltainen kohtalaisesti. Ohjelma varoittaa,
jos ilmoitus näyttäisi vaativan korttia tai pätevyyttä, jonka tilaksi on
asetettu `unknown` tai `no`.

Kun sama työpaikka löytyy esimerkiksi työnantajan sivulta, Duunitorilta ja
Joblystä, ohjelma yhdistää sen yhdeksi riviksi yrityksen, tehtävänimikkeen ja
paikkakunnan perusteella. Työkalurivin **Lähdelinkit**-painikkeesta näkee kaikki
saman ilmoituksen osoitteet. Haetuksi merkitty tila säilyy yhdistämisessä.

## Päivittäinen automaattinen tarkistus

Kun ohjelma toimii käsin:

1. Kaksoisnapsauta `ASENNA_PAIVITTAINEN_AJO.bat`.
2. Hyväksy Windowsin mahdollinen vahvistus.

Tarkistus suoritetaan päivittäin klo 09.00. Ajastuksen voi poistaa tiedostolla
`POISTA_PAIVITTAINEN_AJO.bat`.

## Profiilin muokkaaminen

Hakuprofiilin ja suodattimet voi muuttaa **Avaa asetukset** -painikkeesta:

- `preferred_locations`: parhaat sijainnit
- `acceptable_locations`: muut mahdolliset sijainnit
- `roles`: kiinnostavat tehtävänimikkeet
- `strengths`: pisteytyksessä käytettävät todet vahvuudet
- `qualifications`: 20 yleistä pätevyyttä ja korttia, joiden arvot ovat
  `yes`, `no` tai `unknown`
- `excluded_phrases`: ehdot, joista vähennetään voimakkaasti pisteitä
- `minimum_score`: pienin sopivaksi laskettava pistemäärä

Graafinen asetussivu tarkistaa numerot ja pakolliset tiedot ennen tallennusta.
Vanha `config.json` varmuuskopioidaan automaattisesti ennen muutosta.

Työpaikkalähteet voi rajata tehtäväalaryhmän mukaan. Valittavissa ovat
yleislähteet, varasto ja logistiikka, siivous ja kiinteistöpalvelut, tuotanto
ja rakentaminen, kauppa ja asiakaspalvelu, julkinen sektori sekä ravintola- ja
ruokapalvelut. **Valitse näkyvät** ottaa käyttöön vain parhaillaan näytetyn
ryhmän lähteet. **Poista näkyvät** poistaa saman ryhmän käytöstä.

Sijaintikentissä voi hakea ja valita minkä tahansa Suomen 308 kunnasta tai
19 maakunnasta. Kenttään voi myös kirjoittaa oman alueen, kuten
`pääkaupunkiseutu`. Maakunnan valinta kattaa automaattisesti kaikki sen kunnat:
esimerkiksi `Uusimaa` tunnistaa myös Vantaan, Helsingin, Espoon, Porvoon ja
muut Uudenmaan kunnat. Luokitus perustuu
[Tilastokeskuksen vuoden 2026 kunta–maakunta-avaimeen](https://stat.fi/fi/luokitukset/corrmaps/kunta_1_20260101%23maakunta_1_20260101).

## Lähteet

Versiossa 1.6.3 ovat mukana Posti, Lassila & Tikanoja, SOL, ISS, S-ryhmä,
StaffPoint, WorkPower, Duunitori, Jobly, Laura.fi, Kuntarekry, Helsinki Rekry,
Valtiolle.fi, Bolt.Works, Seure, Kesko, Palmia, Vantti, Eezy, Manpower,
Bondata, Amiko, Worker ja RTK-Henkilöstöpalvelu. Kuusi viimeksi mainittua
lähdettä ovat ensimmäisessä asennuksessa oletuksena pois käytöstä, kunnes
käyttäjä valitsee ne asetuksista.

**Baronan omat työpaikkasivut on jätetty kokonaan pois.** Sivusto palauttaa
automaattiselle haulle HTTP 403 -vastauksen ja vaatii selaimessa suoritettavan
Cloudflare-/bottitarkistuksen. Työpaikkatutka ei yritä kiertää sivuston
suojausta, joten Baronan ilmoituksia ei voida hakea luotettavasti suoraan sen
omilta sivuilta. Baronan työpaikka voi silti löytyä jonkin mukana olevan
yleisen työpaikkapalvelun kautta.

Duunitori hakee varasto-, siivous-, tuotanto-, pihatyö- ja
myymälätyöntekijähakuja pääkaupunkiseudulta. Jobly tarkistaa vastaavat
Uudenmaan tehtäväryhmät. WorkPower haetaan sen julkisesta WordPress-rajapinnasta.
Laura.fi:n haku kohdistuu Uudellemaalle. Kuntarekry ja Valtiolle.fi haetaan
palvelujen julkisista RSS-työpaikkasyötteistä. Laura.fi, Helsinki Rekry ja
Bolt.Works käyttävät Laura.fi:n julkista sivustokarttaa, josta ilmoitukset
rajataan alueen tai työnantajan mukaan. Päättyneen hakuajan ilmoitukset näkyvät
punaisina, kunnes käyttäjä valitsee **Poista listasta**.

Indeed, LinkedIn ja Clevry eivät ole mukana suorassa automaattihaussa, koska ne
vaativat kirjautumista, selainta tai JavaScript-sovellusta. PAM Työpaikat jätettiin
pois, koska sen ilmoitukset tulevat Duunitorilta ja aiheuttaisivat tarpeettomia
kaksoiskappaleita.

Työmarkkinatorin hakurajapinnan käyttö vaatii erillisen yritystunnukseen
sidotun käyttöoikeuden, joten sitä ei voi ottaa käyttöön tavallisena julkisena
automaattihakuna ilman rajapintasopimusta.

## Uuden yrityksen lisääminen

Lisää `sources`-listaan esimerkiksi:

```json
{
  "name": "Yrityksen nimi",
  "type": "html",
  "url": "https://yritys.fi/avoimet-tyopaikat",
  "link_patterns": [
    "yritys\\.fi/avoimet-tyopaikat/.+"
  ],
  "exclude_titles": [
    "avoin hakemus"
  ],
  "enabled": true
}
```

`link_patterns` käyttää säännöllisiä lausekkeita. Jos sivu muuttuu tai lataa
paikat vain JavaScriptillä, tavallinen HTML-haku ei välttämättä näe niitä.
Ohjelma jatkaa muiden lähteiden tarkistamista ja näyttää virheen lokissa.

## Version 1.6.3 muutokset

- Pääikkunaan on lisätty **Haetut työpaikat** -painike.
- Haettujen työpaikkojen näkymässä näkyvät työnantaja, työtehtävä ja
  hakupäivä.
- Hakupäivä tallentuu automaattisesti, kun työpaikka merkitään haetuksi.
- Haettu työpaikka säilyy hakuhistoriassa, vaikka se poistetaan myöhemmin
  tavallisesta työpaikkalistasta.
- Ennen versiota 1.6.3 haetuksi merkittyjen paikkojen tarkkaa hakupäivää ei ole
  tallennettu. Ne säilyvät historiassa merkinnällä **Ei tallennettu**.
- Haettujen työpaikkojen ikkuna käyttää samaa Windowsin vaaleaa tai tummaa
  teemaa ja sovelluskuvaketta kuin pääikkuna.
- Päivitys säilyttää nykyisen `config.json`-tiedoston, tietokannan ja kaikki
  aikaisemmat Haettu-merkinnät.

## Version 1.6.2 muutokset

- Korjattu sijaintisuodatus käyttämään ensisijaisesti ilmoituksen varsinaista
  sijaintikenttää.
- Valittujen alueiden ulkopuoliset tunnistetut kunnat ja maakunnat, kuten
  Kouvola ja Kymenlaakso, eivät enää näy työpaikkalistassa.
- Ilmoituksen kuvauksessa mainittu Helsinki, Uusimaa tai muu valittu alue ei
  enää ohita ilmoituksen varsinaista sijaintia.
- Jos HTML-sivu on lisännyt sijaintikenttään virheellisesti pitkän luettelon
  kuntia, tehtävänimessä oleva selkeä paikkakunta asetetaan etusijalle.
- Korjaus suodattaa myös tietokannassa jo olevat väärän alueen ilmoitukset;
  käyttäjän ei tarvitse poistaa niitä käsin.
- Nykyinen `config.json`, `data/jobs.db`, hakuhistoria sekä **Haettu**,
  **Poistettu** ja **Uudelleen julkaistu** -tilat säilyvät muuttumattomina.

## Versio 1.6.1 – ensimmäinen julkinen julkaisu

Versio 1.6.1 sisältää Työpaikkatutkan kaikki ensimmäisen julkisen julkaisun
ominaisuudet:

- Työpaikkailmoituksia haetaan 24 valittavasta suomalaisesta yritys- ja
  työpaikkalähteestä.
- Työpaikkalähteitä voi suodattaa tehtäväalan mukaan ja ottaa näkyvän ryhmän
  käyttöön tai pois käytöstä yhdellä painikkeella.
- Eezy käyttää sen avoimien työpaikkojen sivun julkista työpaikkahakua.
  Ilmoituksesta luetaan tehtävä, yritys, sijainnit, kuvaus sekä haun alkamis- ja
  päättymisaika.
- Baronan omat sivut on jätetty pois niiden HTTP 403 -eston ja
  Cloudflare-/bottitarkistuksen vuoksi. Työpaikkatutka ei kierrä sivustojen
  suojauksia.
- Ilmoitukset pisteytetään kiinnostavien työtehtävien, sijaintien, vahvuuksien,
  pätevyyksien, korttien ja poissulkevien ilmausten perusteella.
- Sijaintitunnistus kattaa kaikki Suomen 308 kuntaa ja 19 maakuntaa.
  Maakunnan valinta kattaa automaattisesti sen kunnat, ja valittavana on myös
  **Koko Suomi**.
- Sijainteja voi hakea kirjoittamalla, valita ehdotuksista tai lisätä omana
  sijaintina.
- Kiinnostavien työtehtävien valikossa on 481 Suomessa käytössä olevaa
  TK10-ammattiluokkaa. Oman tehtävänimikkeen voi lisätä luettelon ulkopuolelta.
- Vahvuuksien haettavassa valikossa on yli 120 vaihtoehtoa. Myös omat
  vahvuudet ja poissulkevat ilmaukset voi lisätä.
- Graafisessa asetussivussa ovat erilliset **Profiili**, **Haku**,
  **Pätevyydet ja kortit** sekä **Työpaikkalähteet** -välilehdet.
- Käyttöliittymä seuraa Windowsin vaaleaa tai tummaa teemaa. Myös ikkunan
  yläpalkki, painikkeet, taulukko, valitsimet ja tutka–suurennuslasi-kuvake on
  sovitettu samaan teemaan.
- Sama työpaikka yhdistetään yhdeksi ilmoitukseksi yrityksen,
  tehtävänimikkeen ja sijainnin perusteella. Kaikki löydetyt lähdeosoitteet
  säilyvät **Lähdelinkit**-näkymässä.
- SQLite-tietokanta säilyttää hakuhistorian sekä **Haettu**, **Poistettu** ja
  **Uudelleen julkaistu** -tilat.
- Päättyneet haut näkyvät punaisina, kunnes käyttäjä poistaa ne itse.
  Uudella hakuajalla julkaistu sama ilmoitus tunnistetaan uudelleen julkaistuksi.
- Työpaikat voi järjestää pisteiden tai hakuajan mukaan. Hakuajasta näytetään
  vain päivämäärä muodossa `pp.kk.vvvv`.
- Tarkistuksen voi käynnistää käsin tai ajastaa suoritettavaksi päivittäin
  Windowsin Tehtävien ajoituksella.
- Työpaikkatutka ei lähetä hakemuksia tai sähköpostia automaattisesti.
  Hakemuksen lähettäminen jää aina käyttäjän omaksi päätökseksi.
- Julkaisupaketti ei sisällä käyttäjän `config.json`-tiedostoa,
  `data/jobs.db`-tietokantaa, lokitiedostoja tai raportteja.
- Mukana on omistusoikeudellinen `LICENSE`, jossa kaikki oikeudet pidätetään,
  sekä `NOTICE.md`, jossa mainitaan Tilastokeskuksen kunta- ja
  ammattiluokitusaineistojen CC BY 4.0 -lisenssi ja lähteet.

## Julkaisua edeltänyt kehityshistoria

Seuraavat versionumerot olivat sisäisiä kehitysversioita. Niitä ei ole
julkaistu tai tarjottu ladattaviksi.

### Sisäinen versio 1.6.0

- Työpaikkalähteitä on nyt 24.
- Uusina valittavina lähteinä ovat Eezy, Manpower, Bondata, Amiko, Worker ja
  RTK-Henkilöstöpalvelu.
- Lähteitä voi suodattaa tehtäväalaryhmän mukaan, esimerkiksi **Varasto ja
  logistiikka** tai **Siivous ja kiinteistöpalvelut**.
- Näkyvän ryhmän lähteet voi ottaa käyttöön tai poistaa käytöstä yhdellä
  painikkeella. Kokonaismäärä ja käytössä olevien lähteiden määrä näkyvät
  asetuksissa.
- Uudet lähteet ovat oletuksena pois käytöstä, eivätkä ne hidasta hakua ennen
  käyttäjän omaa valintaa.
- Baronan omat lähteet poistetaan asetuksista myös silloin, jos niitä on jäänyt
  vanhaan `config.json`-tiedostoon.
- Nykyiset lähdevalinnat, profiili, tietokanta ja **Haettu**-merkinnät säilyvät.

### Sisäinen versio 1.5.6

- Hiiren rulla vierittää valintalistaa ilman, että Asetukset-sivu liikkuu
  samalla taustalla.
- Pääsivu pysyy paikallaan myös listan ylä- ja alareunassa.
- Korjaus koskee Profiili-sivun kaikkia viittä valintalistaa, niiden
  vierityspalkkeja ja kirjoitettaessa näkyviä ehdotuslistoja.

### Sisäinen versio 1.5.5

- Kaikkien profiilivalitsinten valittujen arvojen listaa on kasvatettu
  alaspäin kahdella rivillä.
- Jokaisessa listassa näkyy nyt kahdeksan riviä aiemman kuuden sijaan.
- Ehdotuslistan ja kirjoituskentän toiminta säilyy ennallaan.

### Sisäinen versio 1.5.4

- Korjattu virhe, jossa automaattisesti avautuva ehdotusvalikko vei
  kirjoituskohdistuksen jo ensimmäisen kirjaimen jälkeen.
- Ehdotukset näkyvät nyt erillisessä listassa kirjoituskentän alla. Kenttään
  voi kirjoittaa koko hakusanan yhtäjaksoisesti.
- Ehdotuksen voi valita hiirellä tai siirtyä listaan nuolinäppäimellä.
- Kaikki profiilin valitsimet ovat oikeasti koko sivun levyisiä, saman
  korkuisia ja yhdenmukaisesti aseteltuja.
- Nykyiset asetukset, omat arvot ja valinnat säilyvät päivityksessä.

### Sisäinen versio 1.5.3

- **Poissulkevat ilmaukset** on muutettu samanlaiseksi haettavaksi
  lisäysvalikoksi kuin sijainnit, työtehtävät ja vahvuudet.
- Kaikki profiilin viisi valitsinta ovat nyt yhdenmukaisia, koko sivun levyisiä
  ja saman korkuisia. Pitkiä nimiä voi tarkastella vaakavierityksellä.
- Valmiina ehdotuksina ovat vain aiemmat seitsemän poissulkevaa ilmausta.
  Uusia valmiita ehtoja ei ole lisätty.
- Oman poissulkevan ilmauksen voi kirjoittaa ja lisätä **Lisää**-painikkeella
  tai Enterillä.
- Aiemmin valitut ja itse lisätyt poissulkevat ilmaukset säilyvät päivityksessä.

### Sisäinen versio 1.5.2

- **Kiinnostavat työtehtävät** on muutettu samanlaiseksi haettavaksi
  valitsimeksi kuin sijainnit ja vahvuudet.
- Valikossa on kaikki 481 Suomessa käytössä olevaa virallista TK10-
  ammattiluokkaa. Luokitus on Tilastokeskuksen julkaisema ja siitä on poistettu
  Suomessa käyttämättömät ammattiluokat.
  [Tilastokeskuksen TK10-ammattiluokitus](https://stat.fi/fi/luokitukset/ammatti/ammatti_17_20210101)
- Työtehtäviä voi hakea kirjoittamalla esimerkiksi `varasto`, jolloin näkyviin
  tulevat siihen sopivat ammattiluokat.
- Jos tehtävää ei löydy valmiista luettelosta, oman tehtävänimikkeen voi lisätä
  **Lisää**-painikkeella tai Enterillä.
- Ammattiluokkien monikkomuodot tunnistetaan pisteytyksessä myös yksittäisen
  työpaikan nimikkeestä. Esimerkiksi `Varastonhoitajat ym.` tunnistaa
  `Varastonhoitaja`-ilmoituksen.
- Aiemmin valitut kiinnostavat työtehtävät säilyvät päivityksessä.

### Sisäinen versio 1.5.1

- Kuntaa tai maakuntaa kirjoitettaessa sopivat vaihtoehdot avautuvat heti
  näkyviin. Esimerkiksi `vant` näyttää valinnan `Vantaa — kunta`.
- Jos kirjoitettua sijaintia ei löydy valmiista luettelosta, sen voi lisätä
  omana sijaintina **Lisää**-painikkeella tai Enterillä.
- **Vahvuudet** on muutettu samanlaiseksi haettavaksi valitsimeksi.
- Mukana on yli 120 yleistä työelämän vahvuutta, työtapaa ja osaamista.
  Luettelon ulkopuolisen oman vahvuuden voi edelleen kirjoittaa ja lisätä.
- Aiemmin valitut sijainnit ja vahvuudet säilyvät päivityksessä.

### Sisäinen versio 1.5.0

- Sijaintitunnistus kattaa kaikki Suomen 308 kuntaa ja 19 maakuntaa vuoden
  2026 virallisen aluejaon mukaan.
- **Parhaat sijainnit** ja **Muut sopivat sijainnit** ovat nyt haettavia
  valitsimia. Listalta voi valita kunnan tai maakunnan, mutta oman sijainnin
  voi edelleen kirjoittaa.
- Maakunnan valinta laajenee automaattisesti sen kuntiin. Esimerkiksi
  `Uusimaa` hyväksyy kaikki Uudenmaan 26 kuntaa.
- Muissa varmasti tunnistetuissa kunnissa olevat ilmoitukset rajataan listan
  ulkopuolelle. Ilmoitus, jonka sijaintia ei pystytä tunnistamaan, jätetään
  näkyviin käyttäjän tarkistettavaksi.
- Valinta **Koko Suomi** hyväksyy työpaikat sijainnista riippumatta.
- Tunnistus ymmärtää myös yleisiä taivutusmuotoja, kuten `Vantaalla`,
  `Helsingissä` ja `Rovaniemellä`.
- Tietokanta, asetukset ja kaikki työpaikkojen tilat säilyvät.

### Sisäinen versio 1.4.7

- **Haku päättyy** -otsikon kirjoitusasu on yhtenäistetty koko sovelluksessa.
- Hakuajan sarakkeessa näytetään vain päivä, kuukausi ja vuosi muodossa
  `pp.kk.vvvv`, esimerkiksi `30.07.2026`.
- Kellonaikaa ei enää näytetä työpaikkalistassa tai HTML-koosteessa.
- Päivämäärälajittelu käyttää edelleen alkuperäistä tallennettua arvoa.
- Tietokanta, asetukset ja kaikki työpaikkojen tilat säilyvät.

### Sisäinen versio 1.4.6

- Profiilista on poistettu nimi, puhelinnumero, sähköposti, portfolio ja
  kotikaupunki. Työpaikkatutka ei tarvitse niitä työpaikkojen keräämiseen.
- **Haku** ja **Pätevyydet ja kortit** ovat nyt omat välilehtensä.
- Pätevyysvalikoima on laajennettu neljästä 20 yleiseen ajokorttiin,
  työlupaan, turvallisuuskorttiin ja palvelualan pätevyyteen.
- Jokaiselle pätevyydelle voi valita tilan **Kyllä**, **Ei** tai **En tiedä**.
- Baronan kolme lähdettä poistetaan myös vanhasta `config.json`-tiedostosta
  ensimmäisellä käynnistyskerralla.
- Ennen asetusten päivitystä tehdään automaattinen varmuuskopio.
- Tietokanta ja kaikki työpaikkojen tilat säilyvät.

### Sisäinen versio 1.4.5

- Asetusten valittu välilehti näkyy nyt muita suurempana; valitsemattomat
  välilehdet ovat pienempiä ja niiden välissä on selkeät raot.
- Välilehtien ja painikkeiden vaaleat käyttöjärjestelmäkehykset on poistettu.
- Painikkeissa on kevyt kahdeksan pikselin pyöristys ja teemaan sopivat
  osoitinvärit.
- Työpaikkalähteiden pienet X-ruudut on korvattu suuremmilla syaaneilla
  valintaruuduilla ja selkeällä valintamerkillä.
- **Tallenna asetukset** on siirretty asetussivun oikeaan yläkulmaan. Sen alla
  muistutetaan tallentamaan ennen sivun sulkemista.
- Tietokanta, asetukset ja kaikki työpaikkojen tilat säilyvät.

### Sisäinen versio 1.4.4

- Korjattu tutkaikonin puuttuminen sovelluksen omasta Windows-yläpalkista.
- Pieni 16×16- ja suuri 32×32-kuvake asetetaan nyt suoraan Windows-ikkunalle
  natiivilla `WM_SETICON`-toiminnolla sekä pää- että asetusikkunassa.
- ICO-tiedoston kaikki seitsemän kokoa tallennetaan Windowsin laajasti
  tukemassa BMP/DIB-muodossa.
- Työpöytäpikakuvake, tietokanta, asetukset ja työpaikkojen tilat säilyvät.

### Sisäinen versio 1.4.3

- Korjattu version 1.4.2 tiedostonimen vaihdon rikkoma vanha pikakuvake.
- `job_agent.py` toimii nyt yhteensopivuuskäynnistimenä ja avaa
  `tyopaikkatutka.py`-ohjelman.
- `ASENNA.bat` luo työpöydälle uuden **Työpaikkatutka**-pikakuvakkeen, joka
  käyttää oikeaa Pythonin ikkunakäynnistintä ja tutkaikonia.
- Pikakuvakkeen voi luoda uudelleen tiedostolla `LUO_PIKAKUVAKE.bat`.
- Nykyinen tietokanta, asetukset ja kaikki työpaikkojen tilat säilyvät.

### Sisäinen versio 1.4.2

- Sovelluksen nimi on nyt **Työpaikkatutka**. Käyttäjän nimi tai agentti-sana
  eivät enää näy sovelluksen nimessä.
- Pääikkunan, asetusikkunan, raporttien, komentorivin, ohjeiden ja ajastetun
  tehtävän nimet on päivitetty.
- Oletusarvoinen höyhenkuvake on korvattu tummansiniseen–syaaniin teemaan
  sopivalla tutka–suurennuslasi-kuvakkeella.
- Varsinaisen ohjelmatiedoston nimi on nyt `tyopaikkatutka.py`.
- Nykyinen `config.json`, `data/jobs.db`, hakuhistoria sekä **Haettu**,
  **Poistettu** ja **Uudelleen julkaistu** -tilat säilyvät.

### Sisäinen versio 1.4.1

- Sähköpostikooste, SMTP-asetukset, sovellussalasana ja **Sähköposti**-
  välilehti on poistettu.
- Käsin ja ajastetusti tehtävä tarkistus vain kerää, pisteyttää ja tallentaa
  työpaikkailmoitukset sovellukseen.
- Vanhojen versioiden sähköpostiasetukset poistetaan `config.json`-
  tiedostosta päivityksen yhteydessä tehdyn varmuuskopion jälkeen.
- Mahdollista vanhaa `.env`-tiedostoa ei käytetä eikä poisteta
  automaattisesti.
- Nykyinen tietokanta sekä **Haettu**, **Poistettu** ja
  **Uudelleen julkaistu** -tilat säilyvät.

### Sisäinen versio 1.4.0

- **Avaa asetukset** avaa nyt teemallisen graafisen asetussivun JSON-tiedoston
  sijaan.
- Välilehdiltä voi muuttaa profiilia, sijainteja, kiinnostavia työtehtäviä,
  vahvuuksia, hakurajoja, pätevyyksiä ja työpaikkalähteitä.
- Lomake tarkistaa arvot ja tekee vanhasta asetustiedostosta varmuuskopion
  ennen tallennusta.
- Asetusikkuna ja sen Windows-otsikkopalkki seuraavat vaaleaa tai tummaa teemaa
  myös ikkunan ollessa auki.
- Päivitys ei muuta tietokantaa tai työpaikkojen tiloja.

### Sisäinen versio 1.3.8

- **Pisteet**-otsikon ensimmäinen klikkaus järjestää eniten pisteitä saaneet
  työpaikat ensin ja seuraava klikkaus vähiten pisteitä saaneet ensin.
- Otsikon nuoli ja alareunan tilateksti näyttävät pistejärjestyksen suunnan.
- Piste- ja määräpäivälajittelusta vain toinen on kerrallaan käytössä, jotta
  listan järjestys pysyy yksiselitteisenä.
- Päivitys ei muuta tietokantaa, asetuksia tai työpaikkojen tiloja.

### Sisäinen versio 1.3.7

- Taulukon tummaan teemaan jäänyt vaalea sisäreuna on poistettu.
- **Haku päättyy** -otsikon ensimmäinen klikkaus järjestää aikaisimmin
  päättyvät haut ensin ja seuraava klikkaus myöhemmin päättyvät ensin.
- Otsikon nuoli ja alareunan tilateksti näyttävät käytössä olevan
  lajittelusuunnan.
- Ilmoitukset, joilla ei ole tunnistettavaa määräpäivää, jäävät molemmissa
  lajittelusuunnissa listan loppuun.
- Päivitys ei muuta tietokantaa, asetuksia tai työpaikkojen tiloja.

### Sisäinen versio 1.3.6

- Tumma ulkoasu käyttää nyt portfolion laivastonsinisiä pintoja ja syaaneja
  korostusvärejä.
- Painikkeet, taulukon otsikot, vierityspalkki, valintaruutu ja etenemispalkki
  on sovitettu samaan väriteemaan ilman kirkkaita valkoisia reunuksia.
- Windowsin natiivi otsikkopalkki sekä pienennys-, suurennus- ja sulkupainikkeet
  seuraavat sovelluksen vaaleaa tai tummaa teemaa.
- Vaalea tila käyttää saman sinisyaanin tyylin vaaleaa vastinetta.
- Päivitys ei muuta tietokantaa, asetuksia tai työpaikkojen tiloja.

### Sisäinen versio 1.3.5

- Sovellus seuraa automaattisesti Windowsin sovellustilaa ja käyttää sen
  mukaista vaaleaa tai tummaa ulkoasua.
- Ulkoasu vaihtuu myös sovelluksen ollessa auki, jos Windowsin teema vaihdetaan.
- Taulukon tila- ja varoitusväreillä on vaaleaan ja tummaan tilaan sovitetut
  vastineet.
- Päivitys ei muuta tietokantaa, hakuhistoriaa eikä **Haettu**, **Poistettu** tai
  **Uudelleen julkaistu** -tiloja.

### Sisäinen versio 1.3.4

- Hakemusluonnos-toiminto ja sen painike on poistettu kokonaan.
- Ohjelma ei enää luo uusia `hakemus_*.txt`-tiedostoja.
- **Merkitse haetuksi** säilyy ennallaan työkalurivillä.
- Kaksoisnapsautus avaa nyt valitun työpaikkailmoituksen.
- **Lähdelinkit** on siirretty omaksi painikkeekseen työkaluriville.
- Nykyinen tietokanta sekä **Haettu**, **Poistettu** ja
  **Uudelleen julkaistu** -tilat säilyvät.

### Sisäinen versio 1.3.3

- Jos aiemmin päättynyt ilmoitus saa uuden voimassa olevan hakuajan, se
  palautetaan listaan tilassa **Uudelleen julkaistu** ja käsitellään uutena.
- Tunnistus toimii myös silloin, kun työnantaja käyttää samaa ilmoitusosoitetta.
- Pelkkä ilmoituksen löytyminen uudelleen ilman uutta määräpäivää ei muuta
  **Poistettu**- tai **Haettu**-tilaa.
- Päivityksen asentaminen ei muuta tietokannan nykyisiä rivejä tai tiloja.
  **Haettu**-merkinnät säilyvät.

### Sisäinen versio 1.3.2

- Päättyneen hakuajan työpaikat säilyvät listassa ja näkyvät punaisina.
- Päättyneitä paikkoja ei käsitellä uusina sopivina työpaikkoina.
- **Ohita**-painike on nimetty **Poista listasta** -painikkeeksi. Poisto
  säilyy myös seuraavissa tarkistuksissa.
- Vanha tietokanta ja kaikki **Haettu**-merkinnät säilyvät päivityksessä.

### Sisäinen versio 1.3.1

- Korjattu Kuntarekry ja Valtiolle.fi käyttämään toimivia RSS-syötteitä
  puuttuvien `sitemap.xml`-osoitteiden sijaan.
- Korjattu Laura.fi, Helsinki Rekry ja Bolt.Works käyttämään Laura.fi:n
  julkista sivustokarttaa ja työnantajakohtaisia osoiterajauksia.
- Version 1.3 vanhat lähdeasetukset korjataan käynnistyksessä automaattisesti.
  Lähteen käytössä/pois-valinta, omat asetukset, tietokanta ja `Haettu`-merkinnät
  säilyvät.

### Sisäinen versio 1.3

- Lisätty Laura.fi, Kuntarekry, Helsinki Rekry, Valtiolle.fi, Bolt.Works,
  Seure, Kesko, Palmia ja Vantti.
- Lisätty XML-sivustokarttojen tuki JavaScriptillä toimiville julkisille
  työpaikkalistoille.
- Jo päättyneet ilmoitukset ohitetaan automaattisesti, kun määräpäivä on
  ilmoituksessa tunnistettavassa muodossa.
- Päivitys lisää uudet lähteet nykyiseen `config.json`-tiedostoon muuttamatta
  omia yhteystietoja, suodattimia tai lähdevalintoja.
- Nykyinen tietokanta, hakuhistoria ja **Haettu**-merkinnät säilyvät.

### Sisäinen versio 1.2

- Lisätty StaffPoint, WorkPower, Duunitori ja Jobly.
- Sama ilmoitus yhdistetään yrityksen, tehtävänimikkeen ja paikkakunnan
  perusteella myös eri lähteiden välillä.
- Kaikki yhdistetyn ilmoituksen lähdelinkit tallennetaan.
- Vanhan v1.1-tietokannan rakenne päivitetään automaattisesti ja
  **Haettu**-merkinnät säilytetään.
- Tietokannasta ja asetuksista tehdään varmuuskopio ennen päivitystä.
- Oletusprofiilin B-ajokortin tilaksi on asetettu `no`, jotta ajokorttia vaativat työt
  saavat selkeän varoituksen ja pistevähennyksen.

## Tiedostot

- `tyopaikkatutka.py`: varsinainen ohjelma
- `job_agent.py`: kevyt käynnistin, joka avaa varsinaisen Työpaikkatutkan
- `LUO_PIKAKUVAKE.bat`: luo Työpaikkatutkan työpöytäpikakuvakkeen uudelleen
- `assets/tyopaikkatutka.png` ja `assets/tyopaikkatutka.ico`: sovelluskuvakkeet
- `config.default.json`: uuden asennuksen oletusasetukset
- `LICENSE`: Työpaikkatutkan omistusoikeudellinen lisenssi
- `NOTICE.md`: kolmansien osapuolten aineistot ja niiden lisenssit
- `config.json`: omat asetukset; luodaan asennuksessa eikä kuulu
  julkaisupakettiin
- `data/jobs.db`: hakuhistoria (syntyy ensimmäisellä ajolla)
- `raportit/`: HTML-koosteet tarkistusten tuloksista
- `logs/tyopaikkatutka.log`: tekninen loki
- `varmuuskopiot/`: automaattiset kopiot päivitystä edeltävistä tiedoista

## Tietoturva ja rajat

- Työpaikkatutka ei kierrä kirjautumisia, CAPTCHA-tarkistuksia tai sivustojen
  estoja.
- Tarkista aina hakemuksen tiedot ennen lähettämistä.
- Jos ilmoituksessa on pakollinen pätevyys, varmista se itse alkuperäisestä
  ilmoituksesta.
- Työnantajien sivurakenteet voivat muuttua. Lähteen asetuksia voidaan silloin
  joutua päivittämään.

## Lisenssi ja tekijänoikeudet

Copyright © 2026 Miika Väyrynen. Kaikki oikeudet pidätetään.

Työpaikkatutkan lähdekoodin, dokumentaation, sovelluskuvakkeiden ja muiden
alkuperäisten materiaalien kopiointi, muuttaminen, jatkokehittäminen, jakaminen
tai uudelleenjulkaiseminen on kielletty ilman tekijänoikeuden haltijan
etukäteen antamaa kirjallista lupaa. Projektin julkinen saatavuus GitHubissa ei
tarkoita avoimen lähdekoodin lisenssin myöntämistä. Tarkemmat ehdot ovat
[`LICENSE`](LICENSE)-tiedostossa.

Kunta- ja ammattiluokitustiedot: **Tilastokeskus, CC BY 4.0**.
Lähteet ovat Tilastokeskuksen **Kunnat 2026** -luokitus ja
**TK10-ammattiluokitus**. Tarkemmat lähde- ja lisenssitiedot ovat
[`NOTICE.md`](NOTICE.md)-tiedostossa.
