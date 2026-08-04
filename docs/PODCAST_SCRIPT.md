# Power Is a Permit, Not a Price
### Podcast script — approx. 15 minutes, two hosts

**Format note.** ALEX narrates the research. SAM is the sceptic and asks the
questions a listener would. Numbers are written the way they should be
*spoken*, not the way they appear in the paper. Every figure traces to a CSV
in `data/final/`; the bracketed sources are for the producer, not to be read
aloud.

---

## COLD OPEN

**ALEX:** I want to start with two numbers.

The first one is a dollar thirty. That's what it's worth, per year, to have
the right to switch off an AI chip when electricity gets expensive. Per GPU.
Per year. A dollar thirty, in the worst region I measured.

**SAM:** And the second?

**ALEX:** Thirty-two thousand, two hundred and ninety-eight dollars. Also per
GPU, per year. That's the gap between what Microsoft charges you to rent the
exact same chip in Virginia versus Amsterdam. Same silicon. Same company.
Thirty per cent more, because it's in the Netherlands.

**SAM:** So the pricing decision is —

**ALEX:** — about twenty-five thousand times bigger than the physics. And
almost everyone building AI infrastructure right now is optimising the
physics.

*[Sources: curtailment_option_value.csv; compute_price_observations.csv,
$12.29 eastus vs $15.977 westeurope, times 8,760 hours.]*

---

## PART ONE — WHAT WE SET OUT TO TEST

**SAM:** Back up. What was the original question?

**ALEX:** There's an idea that's become close to conventional wisdom. It goes:
GPUs eat enormous amounts of power. Power costs money. Power costs vary a lot
by region — the usual claim is about a factor of three. So there should be
something like a merit order for compute.

**SAM:** Merit order meaning —

**ALEX:** Borrowed from electricity markets. Plants get dispatched cheapest
first, and when demand falls the expensive ones switch off in a predictable
sequence. The claim is compute works the same way: as prices fall, expensive
regions go dark first, in order.

**SAM:** That's a clean story.

**ALEX:** Very clean. It's also borrowed from an industry where fuel is sixty
to ninety per cent of the cost of running the plant. So the first thing to
check is whether electricity is anything like that share for a GPU.

**SAM:** And it isn't.

**ALEX:** It's between about half a per cent and fourteen per cent, depending
entirely on which rental price you compare it against. At list price for the
newest chips, it's about one per cent. Fuel for a gas plant is sixty to
ninety. The analogy is off by roughly a factor of fifty on the one ratio that
decides whether it means anything.

---

## PART TWO — I GOT THIS WRONG TWICE

**SAM:** You said you measured this. What did you actually build?

**ALEX:** European electricity prices — every settlement period, four years,
seven regions I'm legally allowed to republish. Two hundred and fifteen
thousand hourly observations, against nine published GPU rental prices.
All free, all auditable, the whole thing rebuilt by a test suite.

**SAM:** And the first answer?

**ALEX:** That nothing ever goes uneconomic. Anywhere. Ever.

**SAM:** But that's wrong.

**ALEX:** That's wrong, and it's wrong in a way I think is genuinely
instructive. I compared each region's *annual average* power price against the
compute price.

**SAM:** And a decision to switch off isn't made against an annual average.

**ALEX:** It's made hour by hour. And when you look hour by hour, Belgium's
most expensive hour is about ten times its own average. It blows straight
through the threshold. So the mechanism does fire — I'd just averaged the
finding out of existence.

**SAM:** How did you catch it?

**ALEX:** I didn't. I had an adversarial reviewer tear the thing apart, and
that was its central objection. Which I think is the actual lesson here: **a
threshold test evaluated on an average tells you nothing about something that
lives in the tail.** I'd made that mistake twice before anyone caught it.

---

## PART THREE — SO WHAT IS IT WORTH?

**SAM:** Fine. Hour by hour. What's the real number?

**ALEX:** The right to switch off is an option — worth something only in the
handful of hours when running would lose money. So price it like one, hour by
hour, over four years.

Austria, the worst region: about a dollar ten per GPU per year. Germany,
thirty-six cents. France —

**SAM:** France?

**ALEX:** Zero. Not "small." Zero. In thirty-one thousand hours of French
electricity data, there was not one single hour where it would have paid to
switch off a GPU.

**SAM:** Over three and a half years.

**ALEX:** Across the board it fires somewhere between half an hour and three
hours a year. So the merit order is real, it's computable, and it is worth
roughly one dollar.

---

## PART FOUR — THE PIVOT

**SAM:** Then this is a null result. Interesting, but — is there an article
here?

**ALEX:** That's exactly the right challenge, and it's what made me go back
for a lot more data. Because "the thing everyone believes is worth a dollar"
is only half a story. The other half is: then why is everyone fighting so
hard over power?

**SAM:** And they clearly are.

**ALEX:** Every serious AI plan opens with electricity. That behaviour is
real. So either everyone is irrational, or they're chasing something that
isn't price.

So I went and got the something else. Generation mix and trade positions for
fifteen countries. National electricity consumption and GDP for thirty —
including the US, China, India, the Gulf, Singapore.

**SAM:** And?

**ALEX:** And I asked a stupid-simple question. One gigawatt of compute
running flat out. What fraction of a country's entire annual electricity is
that?

In the United States: **two tenths of one per cent.**

In China: **one tenth of one per cent.**

In Ireland: **twenty-five point four per cent.**

**SAM:** Twenty-five per cent of Ireland's *national* electricity? For one
cluster?

**ALEX:** For one. And Ireland is a flagship data centre hub. So when Ireland
freezes new data centre connections, that's not politics. That's arithmetic.
Same for Singapore at about fifteen per cent.

---

## PART FIVE — THE NUMBER THAT REFRAMES EVERYTHING

**ALEX:** Now set a limit. Say a compute build-out shouldn't exceed ten per
cent of a country's electricity before it stops being a siting decision and
becomes a national political fight. That gives you the room each country has.

Germany, France, Italy, Spain, the Netherlands, Belgium, Austria, Poland,
Portugal, Sweden, Finland, Denmark, Ireland — **all thirteen, combined:
twenty-six gigawatts.**

**The United States on its own: fifty.**

**China: a hundred and five.**

**SAM:** Thirteen European countries together are half the US.

**ALEX:** Half. And the two destinations the cheap-power story always ends at?
The Nordics — Sweden, Norway, Finland together — have four. The Gulf — Saudi,
UAE, Qatar — have seven point seven.

**SAM:** That's — I want to push back. Isn't ten per cent an arbitrary
threshold?

**ALEX:** Completely arbitrary, and I'd say that in the piece. But move it to
five or twenty and everything scales together. The *ordering* doesn't move,
and the ordering is the point.

**SAM:** Okay. So what's the headline?

**ALEX:** Here's the spine of the whole thing. Four variables, measured, same
dataset.

Electricity price across a continent varies by a factor of **one and a half.**

Firm generation share: about **three.**

GDP across thirty countries: **a hundred and forty-three.**

The ability to physically absorb a gigawatt: **two hundred and sixty-six.**

**SAM:** And price is the flattest.

**ALEX:** Electricity price is the flattest variable in the entire problem.
And it's the only one anyone optimises.

---

## PART SIX — FRANCE AND GERMANY

**SAM:** You said price is a bad measure. Why?

**ALEX:** This is my favourite thing in the data. France and Germany buy
electricity at almost the same price. About eight point three cents versus ten
point four cents a kilowatt-hour, averaged over thirty-one thousand hours
each. Two cents apart.

On the merit-order logic, that's the end of the analysis. Same hub, rounding
error between them.

**SAM:** And they're not the same at all.

**ALEX:** They're not remotely the same. France: seventy-seven per cent of its
generation is dispatchable — you can turn it up when you want it. Its nuclear
fleet alone covers eighty-five per cent of national demand. It's the largest
electricity exporter in Europe, sending out twenty-three per cent of what it
consumes.

Germany: forty-seven per cent dispatchable. Zero nuclear. Net importer.

**SAM:** And a data centre runs —

**ALEX:** Twenty-four hours a day. It doesn't consume an average. It consumes
a *schedule*. **The price series cannot see the difference between those two
countries, and the difference is the entire question.**

That's why the merit order failed. Not because power doesn't matter — because
price is a lossy compression of the thing that actually matters.

---

## PART SEVEN — GRADING THE CONSENSUS

**SAM:** Let's put this against what people are actually claiming. Take
Aschenbrenner's *Situational Awareness* — trillion-dollar clusters, tens of
per cent growth in US electricity, hundreds of millions of GPUs.

**ALEX:** Four claims. I can adjudicate two of them.

**"Tens of per cent growth in US electricity."** Supported — and my data turns
it into a specific quantity. Ten per cent of US electricity is fifty gigawatts
of continuously running compute. That's coherent. But the same ten per cent is
*four tenths of one gigawatt* in Ireland. So it's a claim that only about
three countries on earth can host. It's not a statement about AI. It's a
statement about American exceptionalism.

**SAM:** And hundreds of millions of GPUs?

**ALEX:** Undercut, and this is the one I'd lead with. A hundred million chips
running continuously is a hundred and ten gigawatts. That's more than twice the
entire US absorption limit. Add up all thirty economies in my dataset — every
major economy on earth — and you get two hundred and thirty-one million.

**SAM:** So "hundreds of millions of GPUs" isn't a growth forecast.

**ALEX:** It's a statement that the world's thirty largest economies are
collectively at the ceiling.

**SAM:** And the other two claims?

**ALEX:** Can't adjudicate, and I'll be blunt. Trillion-dollar clusters — I
have no capital cost data. None.

And the big one: is grid *interconnection* the binding constraint? I have zero
rows of queue data. That's the fashionable answer and I can't support it. What
I can say is absorption is the *harder* constraint — you can reform a queue in
one legislative session, but you cannot legislate twenty-five per cent of
Ireland's electricity into existence.

**SAM:** And the scramble for power contracts?

**ALEX:** The behaviour is real. The cost explanation is dead. The entire
European electricity price spread is three hundred and eighty-three dollars
per GPU per year. Nobody is fighting over power contracts to save three
hundred and eighty-three dollars. They're fighting over *whether there is
anywhere to put the thing at all.*

---

## PART EIGHT — WHAT I GOT WRONG, AND WHY IT MATTERS

**SAM:** You've mentioned a couple of your own errors. Why keep bringing them
up?

**ALEX:** Because the whole value of this project is that you can check it —
and that means nothing unless I'm honest about the failure rate.

I averaged away my own finding, twice. I wrote that committed contract rates
were "confidential and unobtainable" while my own code was deliberately
deleting them — Microsoft publishes them, sixty per cent below list, and I was
filtering them out.

I labelled France, the largest electricity exporter in Europe, as a net
importer, because I trusted a sign convention instead of checking it.

And I told people Germany had the largest capacity headroom in Europe. That
came from a row that was a *2030 policy target* sitting alongside present-day
capacity, with double-counted solar and battery gigawatt-*hours* in a gigawatt
column. The real base is about a third of what I said.

**SAM:** So you pulled the number.

**ALEX:** I pulled the whole test. I'd rather have three constraints I trust
than five with a rotten one in the middle. And every one of those was caught
either by an adversarial reviewer or by a test that checks every number in the
write-up against the underlying data. Not by me being careful.

---

## CLOSING

**SAM:** Give me the one sentence.

**ALEX:** Electricity price varies one and a half times across a continent.
The capacity to absorb a gigawatt varies two hundred and sixty-six times
across the world. Everyone is optimising the flattest variable in the problem.

**SAM:** And the practical version?

**ALEX:** Of thirty countries I measured, exactly two have both more than
twenty gigawatts of absorption room and more than ten trillion dollars of GDP.
The United States and China.

There is no third.

**SAM:** What would change your mind?

**ALEX:** Interconnection queue data — I'd want LBNL's *Queued Up* and the
ERCOT large-load queue, because that's the one channel I genuinely can't see.
An American price zone, because right now all my prices are European and most
of my conclusions are about America. And capital costs, which would tell me
whether any of this survives contact with the thing that actually dominates
the cost stack — the chips themselves.

**SAM:** Until then?

**ALEX:** Until then: power is not a price problem. It's a permit problem. And
permits are not evenly distributed.

---

*Every number in this episode traces to a public dataset rebuilt from free,
unauthenticated sources. Sample: 215,082 zone-hours across seven European
bidding zones, 2023–2026; fifteen European grids; thirty national economies;
nine published GPU rental price bases.*
