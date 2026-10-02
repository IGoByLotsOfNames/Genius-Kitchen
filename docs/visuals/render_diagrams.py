"""Render documentation schematics only. Requires matplotlib; no app changes.

Run from any directory: python docs/visuals/render_diagrams.py
The matching example uses the committed recipe definitions, not measured users.
"""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
NAVY, TEAL, GRAY = "#102A43", "#176B87", "#486581"
BG, WHITE, PALE = "#F7F9FC", "#FFFFFF", "#E8F4F5"
plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})


def canvas(title, subtitle, height=5.7):
    fig, ax = plt.subplots(figsize=(11, height))
    fig.patch.set_facecolor(BG)
    ax.set(xlim=(0, 11), ylim=(0, height))
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.text(.4, height-.48, title, fontsize=20, weight="bold", color=NAVY)
    ax.text(.4, height-.88, subtitle, fontsize=11, color=GRAY)
    return fig, ax


def box(ax, x, y, w, h, title, body, fill=WHITE):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.02,rounding_size=.1",
                              facecolor=fill,edgecolor="#CBD5E1",lw=1.1))
    ax.text(x+.17, y+h-.32, title, fontsize=12, weight="bold", color=NAVY)
    ax.text(x+.17, y+h-.61, body, fontsize=10.3, va="top", linespacing=1.6,color=GRAY)


def arrow(ax, a, b, label=None):
    ax.annotate("",xy=b,xytext=a,arrowprops={"arrowstyle":"-|>","lw":1.7,"color":TEAL})
    if label:
        ax.text((a[0]+b[0])/2, (a[1]+b[1])/2+.14,label,ha="center",fontsize=9,color=TEAL)


def save(fig, name):
    for ext in ("svg", "png"):
        fig.savefig(OUT/f"{name}.{ext}", dpi=160, facecolor=BG, metadata={"Date":None} if ext=="svg" else None)
        if ext == "svg":
            path = OUT / f"{name}.{ext}"
            path.write_text("\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)


def architecture():
    fig, ax = canvas("Genius Kitchen / current architecture", "A local desktop interface with small, independently inspectable components.", 6.5)
    box(ax,3.35,3.95,4.3,1.05,"Tkinter interface · app.py","Add / remove ingredients · refresh views",PALE)
    box(ax,.4,1.75,3.2,1.35,"Inventory · inventory.py","Expiry ordering and date filters\nAvailable ingredient names")
    box(ax,3.9,1.75,3.2,1.35,"JSON store · storage.py","Load local inventory\nWrite temporary file → replace")
    box(ax,7.4,1.75,3.2,1.35,"Matcher · recipes.py","Rank coverage and missing names\nRead six bundled recipes")
    arrow(ax,(4.0,3.95),(2,3.13))
    arrow(ax,(5.5,3.95),(5.5,3.13))
    arrow(ax,(7,3.95),(9,3.13))
    ax.text(5.5,3.49,"coordinates",ha="center",fontsize=10,color=TEAL,bbox={"facecolor":BG,"edgecolor":"none"})
    box(ax,.4,.4,10.2,.92,"Shared domain objects · models.py","Ingredient: quantity, unit, category, expiry date     |     Recipe: names, ingredients, instructions",PALE)
    ax.text(.4,1.48,"The interface passes available names from the inventory into the matcher.",fontsize=10.5,color=GRAY)
    save(fig,"architecture")


def matching():
    recipes=json.loads((ROOT/"src/genius_kitchen/data/recipes.json").read_text())
    names={"rice","egg"}
    examples=[r for r in recipes if r["name"] in {"Vegetable Fried Rice","Tomato Omelette"}]
    examples.sort(key=lambda r:-len(names.intersection(r["ingredients"]))/len(r["ingredients"]))
    assert [len(names.intersection(r["ingredients"])) for r in examples]==[2,1]
    fig,ax=canvas("From pantry to an explainable match","Worked example using the bundled recipes. Schematic of the current implementation.",6.2)
    box(ax,.4,2.4,3,2.25,"1 / Check availability","Rice · positive quantity · in date\nEgg · positive quantity · in date\nTomato · expired\n\nAvailable names: rice, egg",PALE)
    arrow(ax,(3.48,3.55),(3.98,3.55))
    for r,y in zip(examples,(3.15,1.4)):
        present=names.intersection(r["ingredients"])
        missing=[n for n in r["ingredients"] if n not in names]
        score=len(present)/len(r["ingredients"])
        box(ax,4.12,y,6.43,1.42,r["name"],f"{len(present)} of {len(r['ingredients'])} ingredient names available  ·  {score:.0%} coverage\nMissing: {', '.join(missing)}")
    ax.text(.4,.63,"2 / Rank by coverage",color=NAVY,fontsize=12,weight="bold")
    ax.text(3.5,.63,"Amounts required and ingredient synonyms are not resolved.",color=GRAY,fontsize=10.5)
    save(fig,"recipe-matching")


if __name__=="__main__":
    architecture()
    matching()
