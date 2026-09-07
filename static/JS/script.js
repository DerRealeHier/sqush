// sqush.io frontend interactions (optimized for smooth 60fps rendering)
document.addEventListener('DOMContentLoaded', () => {

    // Review vote buttons (event delegation instead of one listener per button)
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.vote-btn');
        if (!btn) return;

        const reviewId = btn.getAttribute('data-review-id');
        const voteType = btn.getAttribute('data-vote-type');
        fetch(`/vote_review/${reviewId}/${voteType}`, { method: 'POST' })
            .then(res => {
                if (res.status === 401 || res.redirected) {
                    window.location.href = "/login";
                    return null;
                }
                return res.json();
            })
            .then(data => {
                if (!data) return;
                const cardBody = btn.closest('.card-body');
                if (cardBody) {
                    const helpfulSpan = cardBody.querySelector('.helpful-count');
                    const funnySpan = cardBody.querySelector('.funny-count');
                    if (helpfulSpan && data.helpful !== undefined) helpfulSpan.textContent = data.helpful;
                    if (funnySpan && data.funny !== undefined) funnySpan.textContent = data.funny;
                }
            })
            .catch(err => console.error("Vote Mistake:", err));
    });

    // Wishlist Herz-Buttons (Store-Cards, Home-Cards, Detail-Seite, Wishlist-Seite)
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.wishlist-btn');
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();
        const gameId = btn.getAttribute('data-game-id');

        fetch(`/toggle_wishlist/${gameId}`, { method: 'POST' })
            .then(res => {
                if (res.status === 401 || res.redirected) {
                    // get back to your login!
                    window.location.href = "/login";
                    return null;
                }
                return res.json();
            })
            .then(data => {
                if (!data) return;

                // Sync all wishlist buttons with the same game ID on the page
                document.querySelectorAll(`.wishlist-btn[data-game-id="${gameId}"]`).forEach(b => {
                    const icon = b.querySelector('i');
                    if (data.on_wishlist) {
                        b.classList.add('active');
                        if (icon) {
                            icon.classList.remove('bi-heart');
                            icon.classList.add('bi-heart-fill');
                        }
                    } else {
                        b.classList.remove('active');
                        if (icon) {
                            icon.classList.remove('bi-heart-fill');
                            icon.classList.add('bi-heart');
                        }
                    }
                });

                // when deleting it from the wishlist never see it again on the page
                if (!data.on_wishlist && document.getElementById('wishlistGrid')) {
                    const card = btn.closest('.wishlist-item');
                    if (card) {
                        card.remove();
                        const grid = document.getElementById('wishlistGrid');
                        if (grid && grid.querySelectorAll('.wishlist-item').length === 0) {
                            const emptyMsg = document.getElementById('emptyWishlistMessage');
                            if (emptyMsg) emptyMsg.classList.remove('d-none');
                        }
                    }
                }
            })
            .catch(err => console.error("Wishlist Fehler:", err));
    });

    // Cart system toggle
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".cart-btn");
        if (!btn) return;
        
        e.preventDefault();
        e.stopPropagation();
        
        const gameId = btn.getAttribute("data-game-id");
        const inCart = btn.classList.contains("active");
        const url = inCart ? `/cart/remove/${gameId}` : `/cart/add/${gameId}`;
        
        // Pass the HMAC nonce if available
        const headers = { "Content-Type": "application/json" };
        if (window.squshCartToken) {
            headers["X-Cart-Token"] = window.squshCartToken;
        }

        fetch(url, { method: "POST", headers: headers })
            .then(res => {
                if (res.status === 401 || res.redirected) {
                    window.location.href = "/login";
                    return null;
                }
                if (res.status === 400) {
                    // might be bot protection failed or game already owned
                    return res.json().then(data => { alert(data.error || "Can't do that"); return null; });
                }
                return res.json();
            })
            .then(data => {
                if (!data) return;
                
                // Sync all cart buttons with the same game ID on the page
                document.querySelectorAll(`.cart-btn[data-game-id="${gameId}"]`).forEach(b => {
                    const icon = b.querySelector("i");
                    const label = b.querySelector(".cart-btn-label");
                    if (data.in_cart) {
                        b.classList.add("active");
                        if (icon) icon.classList.replace("bi-cart-plus", "bi-cart-fill");
                        if (label) label.textContent = "IN CART";
                    } else {
                        b.classList.remove("active");
                        if (icon) icon.classList.replace("bi-cart-fill", "bi-cart-plus");
                        if (label) label.textContent = "ADD TO CART";
                    }
                });

                // If we are on the cart page, remove the item's row
                if (!data.in_cart && window.location.pathname === "/cart") {
                    const row = document.getElementById(`cart-item-${gameId}`);
                    if (row) row.remove();
                    window.location.reload();
                }
                
                // Update all badge counts!
                document.querySelectorAll(".cart-count-badge").forEach(badge => {
                    badge.textContent = data.cart_count;
                    if (data.cart_count === 0) badge.classList.add("d-none");
                    else badge.classList.remove("d-none");
                });
            })
            .catch(err => console.error("Cart Fehler:", err));
    });

    // Cart checkout handler
    const cartCheckoutBtn = document.querySelector("#cartCheckoutBtn");
    if (cartCheckoutBtn) {
        fetch("/config")
            .then((result) => result.json())
            .then((data) => {
                const stripe = Stripe(data.publicKey);
                cartCheckoutBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    fetch("/create-cart-checkout-session")
                        .then((result) => {
                            if (result.status === 401 || result.redirected) {
                                window.location.href = "/login";
                                return null;
                            }
                            return result.json();
                        })
                        .then((data) => {
                            if (!data) return;
                            if (data.error) {
                                alert(data.error);
                                return;
                            }
                            return stripe.redirectToCheckout({ sessionId: data.sessionId });
                        })
                        .catch((err) => { console.error("Stripe Cart Fehler:", err); });
                });
            })
            .catch((err) => { console.error("Stripe config Fehler:", err); });
    }

    // Stripe checkout
    // Only hit /config (and init Stripe) on pages that actually have a buy button.
    const submitBtn = document.querySelector("#submitBtn");
    if (submitBtn) {
        fetch("/config")
            .then((result) => result.json())
            .then((data) => {
                const stripe = Stripe(data.publicKey);

                submitBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    const gameId = submitBtn.getAttribute("data-game-id");
                    fetch(`/create-checkout-session/${gameId}`)
                        .then((result) => {
                            if (result.status === 401 || result.redirected) {
                                window.location.href = "/login";
                                return null;
                            }
                            return result.json();
                        })
                        .then((data) => {
                            if (!data) return;
                            if (data.error) {
                                alert(data.error);
                                return;
                            }
                            return stripe.redirectToCheckout({ sessionId: data.sessionId });
                        })
                        .catch((err) => { console.error("Stripe Fehler:", err); });
                });
            })
            .catch((err) => { console.error("Stripe config Fehler:", err); });
    }

    // Tip Jar Modal & Checkout. devs need extra cash (:
    const tipJarModal = document.getElementById("tipJarModal");
    if (tipJarModal) {
        const tipPillBtns = tipJarModal.querySelectorAll(".tip-pill-btn");
        const customContainer = document.getElementById("customTipContainer");
        const customInput = document.getElementById("customTipInput");
        const submitTipBtn = document.getElementById("submitTipBtn");
        const tipMessageInput = document.getElementById("tipMessageInput");
        const supporterNameInput = document.getElementById("supporterNameInput");
        const tipErrorAlert = document.getElementById("tipErrorAlert");

        let currentTipAmount = 5.00;

        function updateSubmitButtonText(amount) {
            if (submitTipBtn) {
                const formatted = (amount || 0).toLocaleString("de-DE", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                });
                submitTipBtn.innerHTML = `<i class="bi bi-heart-fill me-1"></i> SEND ${formatted} € TIP`;
            }
        }

        tipPillBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                tipPillBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");

                const amountVal = btn.dataset.amount;
                if (amountVal === "custom") {
                    if (customContainer) customContainer.classList.remove("d-none");
                    if (customInput) {
                        customInput.focus();
                        const parsed = parseFloat(customInput.value);
                        currentTipAmount = !isNaN(parsed) && parsed > 0 ? parsed : 0;
                    }
                } else {
                    if (customContainer) customContainer.classList.add("d-none");
                    currentTipAmount = parseFloat(amountVal) || 5.00;
                }
                updateSubmitButtonText(currentTipAmount);
            });
        });

        if (customInput) {
            customInput.addEventListener("input", () => {
                const parsed = parseFloat(customInput.value);
                currentTipAmount = !isNaN(parsed) && parsed > 0 ? parsed : 0;
                updateSubmitButtonText(currentTipAmount);
            });
        }

        if (submitTipBtn) {
            submitTipBtn.addEventListener("click", async (e) => {
                e.preventDefault();
                const gameId = submitTipBtn.dataset.gameId;

                // Validate amount
                if (!currentTipAmount || currentTipAmount < 1.00) {
                    if (tipErrorAlert) {
                        tipErrorAlert.textContent = "Please choose an amount of at least 1.00 €.";
                        tipErrorAlert.classList.remove("d-none");
                    }
                    return;
                }

                if (tipErrorAlert) {
                    tipErrorAlert.classList.add("d-none");
                    tipErrorAlert.textContent = "";
                }

                const originalText = submitTipBtn.innerHTML;
                submitTipBtn.disabled = true;
                submitTipBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Processing...`;

                const payload = {
                    amount: currentTipAmount,
                    message: tipMessageInput ? tipMessageInput.value.trim() : "",
                    supporter_name: supporterNameInput ? supporterNameInput.value.trim() : "",
                };

                try {
                    const sessionRes = await fetch(`/create-tip-checkout-session/${gameId}`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                    const sessionData = await sessionRes.json();

                    if (sessionData.error) {
                        if (tipErrorAlert) {
                            tipErrorAlert.textContent = sessionData.error;
                            tipErrorAlert.classList.remove("d-none");
                        }
                        submitTipBtn.disabled = false;
                        submitTipBtn.innerHTML = originalText;
                        return;
                    }

                    if (sessionData.sessionId) {
                        const cfgRes = await fetch("/config");
                        const cfg = await cfgRes.json();
                        if (!cfg.publicKey) {
                            if (tipErrorAlert) {
                                tipErrorAlert.textContent = "Stripe Publishable Key is not configured.";
                                tipErrorAlert.classList.remove("d-none");
                            }
                            submitTipBtn.disabled = false;
                            submitTipBtn.innerHTML = originalText;
                            return;
                        }

                        const stripe = Stripe(cfg.publicKey);
                        const { error } = await stripe.redirectToCheckout({ sessionId: sessionData.sessionId });
                        if (error) {
                            if (tipErrorAlert) {
                                tipErrorAlert.textContent = error.message;
                                tipErrorAlert.classList.remove("d-none");
                            }
                            submitTipBtn.disabled = false;
                            submitTipBtn.innerHTML = originalText;
                        }
                    }
                } catch (err) {
                    console.error("Tip checkout error:", err);
                    if (tipErrorAlert) {
                        tipErrorAlert.textContent = "An error occurred. Please try again.";
                        tipErrorAlert.classList.remove("d-none");
                    }
                    submitTipBtn.disabled = false;
                    submitTipBtn.innerHTML = originalText;
                }
            });
        }
    }

    // Centralized single interval for countdown timers (replaces N intervals with 1)
    const timerElements = document.querySelectorAll(".timer");
    if (timerElements.length > 0) {
        const timerData = [];
        timerElements.forEach(el => {
            const dateStr = el.getAttribute("data-end");
            if (dateStr) {
                timerData.push({
                    el: el,
                    display: el.querySelector(".countdown"),
                    endTime: new Date(dateStr).getTime()
                });
            }
        });

        function updateAllTimers() {
            const now = Date.now();
            for (let i = timerData.length - 1; i >= 0; i--) {
                const t = timerData[i];
                const distance = t.endTime - now;
                if (distance <= 0) {
                    t.el.innerHTML = "SALE ENDED";
                    timerData.splice(i, 1);
                } else if (t.display) {
                    const days = Math.floor(distance / 86400000);
                    const hours = Math.floor((distance % 86400000) / 3600000);
                    const minutes = Math.floor((distance % 3600000) / 60000);
                    const seconds = Math.floor((distance % 60000) / 1000);
                    t.display.textContent = `${days}d ${hours}h ${minutes}m ${seconds}s`;
                }
            }
            if (timerData.length === 0) {
                clearInterval(centralTimerInterval);
            }
        }
        updateAllTimers();
        const centralTimerInterval = setInterval(updateAllTimers, 1000);
    }

    // Debounced, in-memory home game search
    const gameSearch = document.getElementById('gameSearch');
    if (gameSearch) {
        const homeItems = Array.from(document.querySelectorAll('#gamesGrid .game-item')).map(item => ({
            el: item,
            title: (item.getAttribute('data-title') || '').toLowerCase(),
        }));
        const noMatchMsg = document.getElementById('noMatchMessage');

        function runGameSearch() {
            const query = gameSearch.value.toLowerCase().trim();
            let visibleCount = 0;
            homeItems.forEach(item => {
                const match = !query || item.title.includes(query);
                if (match) {
                    item.el.classList.remove('d-none');
                    visibleCount++;
                } else {
                    item.el.classList.add('d-none');
                }
            });
            if (noMatchMsg) {
                if (visibleCount === 0 && homeItems.length > 0) {
                    noMatchMsg.classList.remove('d-none');
                } else {
                    noMatchMsg.classList.add('d-none');
                }
            }
        }

        let homeSearchTimer;
        gameSearch.addEventListener('input', () => {
            clearTimeout(homeSearchTimer);
            homeSearchTimer = setTimeout(() => {
                requestAnimationFrame(runGameSearch);
            }, 60);
        });
    }

    // High-performance store filtering with in-memory caching and RAF
    const storeSearch = document.getElementById('storeSearch');
    const genreCheckboxes = document.querySelectorAll('.genre-checkbox');
    const tagCheckboxes = document.querySelectorAll('.tag-checkbox');
    const priceMinFilter = document.getElementById('priceMinFilter');
    const priceMaxFilter = document.getElementById('priceMaxFilter');
    const saleFilter = document.getElementById('saleFilter');
    const clearFiltersBtn = document.getElementById('clearFiltersBtn');
    const rawGameItems = document.querySelectorAll('.store-game-item');
    const genreHeadings = document.querySelectorAll('.genre-heading');
    const storeNoMatchMsg = document.getElementById('storeNoMatchMessage');
    const genreActiveCount = document.getElementById('genreActiveCount');
    const tagActiveCount = document.getElementById('tagActiveCount');
    const genreSearchInput = document.getElementById('genreSearchInput');
    const tagSearchInput = document.getElementById('tagSearchInput');
    const clearGenreSearchBtn = document.getElementById('clearGenreSearchBtn');
    const clearTagSearchBtn = document.getElementById('clearTagSearchBtn');
    const genrePillGroup = document.getElementById('genrePillGroup');
    const tagPillGroup = document.getElementById('tagPillGroup');
    const genrePillEmptyMsg = document.getElementById('genrePillEmptyMsg');
    const tagPillEmptyMsg = document.getElementById('tagPillEmptyMsg');
    const genrePillMatchesCount = document.getElementById('genrePillMatchesCount');
    const tagPillMatchesCount = document.getElementById('tagPillMatchesCount');

    if (storeSearch && priceMinFilter && priceMaxFilter && saleFilter && rawGameItems.length > 0) {
        // Cache game item attributes in memory once to avoid DOM reads & JSON.parse on each keystroke
        const cachedStoreGames = Array.from(rawGameItems).map(item => {
            let tags = [];
            try {
                tags = JSON.parse(item.getAttribute('data-tags') || "[]");
            } catch (err) {
                tags = [];
            }
            return {
                el: item,
                title: (item.getAttribute('data-title') || '').toLowerCase(),
                genre: (item.getAttribute('data-genre') || '').toLowerCase(),
                genreRaw: item.getAttribute('data-genre') || '',
                price: parseFloat(item.getAttribute('data-price')) || 0,
                isSale: item.getAttribute('data-sale') === 'true',
                tagsSet: new Set(tags.map(t => (t || '').toLowerCase())),
            };
        });

        function getCheckedValues(checkboxes) {
            const vals = [];
            for (let i = 0; i < checkboxes.length; i++) {
                if (checkboxes[i].checked) vals.push(checkboxes[i].value.toLowerCase());
            }
            return vals;
        }

        function updateActiveCountBadge(badgeEl, count) {
            if (!badgeEl) return;
            if (count > 0) {
                badgeEl.textContent = `(${count})`;
                badgeEl.classList.remove('d-none');
            } else {
                badgeEl.classList.add('d-none');
            }
        }

        function applyStoreFilters() {
            const query = storeSearch.value.toLowerCase().trim();
            const selectedGenres = getCheckedValues(genreCheckboxes);
            const selectedTags = getCheckedValues(tagCheckboxes);
            const minPrice = parseFloat(priceMinFilter.value);
            const maxPrice = parseFloat(priceMaxFilter.value);
            const onlySale = saleFilter.checked;

            updateActiveCountBadge(genreActiveCount, selectedGenres.length);
            updateActiveCountBadge(tagActiveCount, selectedTags.length);

            let matches = 0;
            const visibleCountByGenre = Object.create(null);

            const hasGenres = selectedGenres.length > 0;
            const hasTags = selectedTags.length > 0;
            const checkMinPrice = !isNaN(minPrice);
            const checkMaxPrice = !isNaN(maxPrice);

            for (let i = 0; i < cachedStoreGames.length; i++) {
                const item = cachedStoreGames[i];
                if (query && !item.title.includes(query)) {
                    item.el.classList.add('d-none');
                    continue;
                }
                if (hasGenres && !selectedGenres.includes(item.genre)) {
                    item.el.classList.add('d-none');
                    continue;
                }
                if (hasTags && !selectedTags.some(t => item.tagsSet.has(t))) {
                    item.el.classList.add('d-none');
                    continue;
                }
                if (checkMinPrice && item.price < minPrice) {
                    item.el.classList.add('d-none');
                    continue;
                }
                if (checkMaxPrice && item.price > maxPrice) {
                    item.el.classList.add('d-none');
                    continue;
                }
                if (onlySale && !item.isSale) {
                    item.el.classList.add('d-none');
                    continue;
                }

                item.el.classList.remove('d-none');
                matches++;
                visibleCountByGenre[item.genreRaw] = (visibleCountByGenre[item.genreRaw] || 0) + 1;
            }

            for (let j = 0; j < genreHeadings.length; j++) {
                const heading = genreHeadings[j];
                const genre = heading.getAttribute('data-genre-heading');
                if (visibleCountByGenre[genre]) {
                    heading.classList.remove('d-none');
                } else {
                    heading.classList.add('d-none');
                }
            }

            if (storeNoMatchMsg) {
                if (matches === 0 && cachedStoreGames.length > 0) {
                    storeNoMatchMsg.classList.remove('d-none');
                } else {
                    storeNoMatchMsg.classList.add('d-none');
                }
            }
        }

        let storeFilterTimer;
        function scheduleStoreFilters() {
            clearTimeout(storeFilterTimer);
            storeFilterTimer = setTimeout(() => {
                requestAnimationFrame(applyStoreFilters);
            }, 60);
        }

        function setupPillSearch(inputEl, clearBtn, groupEl, emptyMsgEl, countEl) {
            if (!inputEl || !groupEl) return null;
            const pills = groupEl.querySelectorAll('.filter-pill');

            function filterPills() {
                const q = inputEl.value.toLowerCase().trim();
                if (clearBtn) {
                    clearBtn.style.display = q ? 'block' : 'none';
                    if (q) clearBtn.classList.remove('d-none');
                    else clearBtn.classList.add('d-none');
                }

                let matches = 0;
                pills.forEach(pill => {
                    const label = pill.querySelector('label');
                    const name = (pill.getAttribute('data-name') || (label ? label.textContent : pill.textContent)).toLowerCase().trim();
                    const checkbox = pill.querySelector('input[type="checkbox"]');
                    const isChecked = checkbox && checkbox.checked;

                    if (!q || name.includes(q) || isChecked) {
                        pill.style.display = 'inline-flex';
                        pill.classList.remove('d-none');
                        if (!q || name.includes(q)) matches++;
                    } else {
                        pill.style.display = 'none';
                        pill.classList.add('d-none');
                    }
                });

                if (emptyMsgEl) {
                    const showEmpty = q && matches === 0;
                    emptyMsgEl.style.display = showEmpty ? 'block' : 'none';
                    if (showEmpty) emptyMsgEl.classList.remove('d-none');
                    else emptyMsgEl.classList.add('d-none');
                }

                if (countEl) {
                    if (q) {
                        countEl.textContent = `(${matches} found)`;
                        countEl.style.display = 'inline';
                        countEl.classList.remove('d-none');
                    } else {
                        countEl.style.display = 'none';
                        countEl.classList.add('d-none');
                    }
                }
            }

            inputEl.addEventListener('input', filterPills);
            inputEl.addEventListener('keyup', filterPills);
            inputEl.addEventListener('change', filterPills);
            inputEl.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    inputEl.value = '';
                    filterPills();
                }
            });

            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    inputEl.value = '';
                    inputEl.focus();
                    filterPills();
                });
            }

            return filterPills;
        }

        const resetGenrePills = setupPillSearch(genreSearchInput, clearGenreSearchBtn, genrePillGroup, genrePillEmptyMsg, genrePillMatchesCount);
        const resetTagPills = setupPillSearch(tagSearchInput, clearTagSearchBtn, tagPillGroup, tagPillEmptyMsg, tagPillMatchesCount);

        storeSearch.addEventListener('input', scheduleStoreFilters);
        priceMinFilter.addEventListener('input', scheduleStoreFilters);
        priceMaxFilter.addEventListener('input', scheduleStoreFilters);
        saleFilter.addEventListener('change', scheduleStoreFilters);
        genreCheckboxes.forEach(cb => cb.addEventListener('change', scheduleStoreFilters));
        tagCheckboxes.forEach(cb => cb.addEventListener('change', scheduleStoreFilters));

        if (clearFiltersBtn) {
            clearFiltersBtn.addEventListener('click', () => {
                storeSearch.value = '';
                priceMinFilter.value = '';
                priceMaxFilter.value = '';
                saleFilter.checked = false;
                genreCheckboxes.forEach(cb => cb.checked = false);
                tagCheckboxes.forEach(cb => cb.checked = false);
                if (genreSearchInput) genreSearchInput.value = '';
                if (tagSearchInput) tagSearchInput.value = '';
                if (resetGenrePills) resetGenrePills();
                if (resetTagPills) resetTagPills();
                applyStoreFilters();
            });
        }

        applyStoreFilters();
    }

    // High-performance Lazy Video Preview on card hover
    document.querySelectorAll('.game-card, .home-sale-card').forEach(card => {
        const slot = card.querySelector('.game-video-slot');
        const localVideo = card.querySelector('video.game-video');
        const videoType = card.getAttribute('data-video-type') || (slot ? slot.dataset.videoType : (localVideo ? 'local' : 'none'));
        if (!videoType || videoType === 'none') return;

        let hoverTimeout = null;

        card.addEventListener('mouseenter', () => {
            hoverTimeout = setTimeout(() => {
                if (videoType === 'youtube') {
                    const ytId = card.getAttribute('data-yt-id') || (slot ? slot.dataset.ytId : null);
                    if (!ytId) return;

                    let iframe = card.querySelector('.game-video-iframe');
                    if (!iframe) {
                        iframe = document.createElement('iframe');
                        iframe.className = 'game-video game-video-iframe';
                        iframe.src = `https://www.youtube-nocookie.com/embed/${ytId}?autoplay=1&mute=1&controls=0&rel=0&playsinline=1&modestbranding=1`;
                        iframe.setAttribute('allow', 'autoplay; encrypted-media');
                        iframe.setAttribute('loading', 'lazy');
                        const wrapper = card.querySelector('.home-card-img-wrapper, .game-img-wrapper');
                        if (wrapper) wrapper.appendChild(iframe);
                    }
                    requestAnimationFrame(() => {
                        if (iframe) iframe.style.opacity = '1';
                    });
                } else if (videoType === 'local' && localVideo) {
                    if (!localVideo.src && localVideo.dataset.src) {
                        localVideo.src = localVideo.dataset.src;
                    }
                    localVideo.style.opacity = '1';
                    localVideo.play().catch(() => {});
                }
            }, 180); // 180ms hover debounce prevents unneeded video loading on quick cursor passing
        });

        card.addEventListener('mouseleave', () => {
            if (hoverTimeout) {
                clearTimeout(hoverTimeout);
                hoverTimeout = null;
            }
            if (videoType === 'youtube') {
                const iframe = card.querySelector('.game-video-iframe');
                if (iframe) {
                    iframe.style.opacity = '0';
                    setTimeout(() => {
                        if (iframe.parentNode) {
                            iframe.src = 'about:blank';
                            iframe.remove();
                        }
                    }, 250);
                }
            } else if (videoType === 'local' && localVideo) {
                localVideo.pause();
                localVideo.style.opacity = '0';
            }
        });
    });

    // Feature: Views, Votes, Follow

    // View count per Update
    const updateViewBadges = document.querySelectorAll(".update-view-count");
    if (updateViewBadges.length > 0) {
        setTimeout(() => {
            updateViewBadges.forEach(badge => {
                const updateId = badge.dataset.updateId;
                fetch(`/update_view/${updateId}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" }
                })
                    .then(res => res.json())
                    .then(data => {
                        if (data && data.views !== undefined) {
                            badge.textContent = `${data.views} Views`;
                        }
                    })
                    .catch(err => console.error("Update view count error:", err));
            });
        }, 5000);
    }

    // up down buttons on update page
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.update-vote-btn');
        if (!btn) return;

        const updateId = btn.dataset.updateId;
        const voteType = btn.dataset.voteType;

        fetch(`/update/${updateId}/vote/${voteType}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        })
            .then(res => {
                if (res.status === 401 || res.redirected) {
                    window.location.href = "/login";
                    return null;
                }
                return res.json();
            })
            .then(data => {
                if (!data || data.upvotes === undefined) return;

                // updating both buttons
                document.querySelectorAll(`.update-vote-btn[data-update-id="${updateId}"]`).forEach(b => {
                    const type = b.dataset.voteType;
                    const countSpan = b.querySelector(type === "up" ? ".up-count" : ".down-count");
                    if (countSpan) {
                        countSpan.textContent = type === "up" ? data.upvotes : data.downvotes;
                    }
                });

                // active only one button at a time
                document.querySelectorAll(`.update-vote-btn[data-update-id="${updateId}"]`).forEach(b => {
                    if (b !== btn) b.classList.remove("active");
                });
                btn.classList.toggle("active");
            })
            .catch(err => console.error("Update vote error:", err));
    });

    // Follow Game Buttons
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.follow-game-btn');
        if (!btn) return;

        const gameId = btn.dataset.gameId;

        fetch(`/follow_game/${gameId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        })
            .then(res => {
                if (res.status === 401 || res.redirected) {
                    window.location.href = "/login";
                    return null;
                }
                return res.json();
            })
            .then(data => {
                if (!data) return;
                // there can be several follow buttons on the page
                document.querySelectorAll(`.follow-game-btn[data-game-id="${gameId}"]`).forEach(b => {
                    const bIcon = b.querySelector("i");
                    if (data.following) {
                        b.classList.add("active");
                        if (bIcon) {
                            bIcon.classList.remove("bi-bell");
                            bIcon.classList.add("bi-bell-fill");
                        }
                    } else {
                        b.classList.remove("active");
                        if (bIcon) {
                            bIcon.classList.remove("bi-bell-fill");
                            bIcon.classList.add("bi-bell");
                        }
                    }
                });
            })
            .catch(err => console.error("Follow game error:", err));
    });

});