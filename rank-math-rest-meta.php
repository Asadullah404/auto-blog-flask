<?php
/**
 * Plugin Name: Rank Math REST Meta (pipeline)
 * Description: Exposes Rank Math's SEO meta fields (title, description, focus keyword,
 *              canonical) to the WordPress REST API so they can be set programmatically.
 *              Works with the FREE version of Rank Math. No Pro required.
 * Version:     1.0
 * Author:      Content Pipeline
 *
 * ── HOW TO INSTALL ────────────────────────────────────────────────────────────
 * 1. On your site, go to:   wp-content/mu-plugins/
 *    (If the "mu-plugins" folder does not exist, create it — exactly that name.)
 * 2. Upload this file into it:  wp-content/mu-plugins/rank-math-rest-meta.php
 * 3. That's it. "mu" = must-use: it activates automatically, there is NO
 *    "Activate" button and it cannot be deactivated from the admin by accident.
 *
 * You can confirm it worked: after your script publishes a post, open it in the
 * WordPress editor — the Rank Math meta title / description / focus keyword boxes
 * should be filled in. If they are blank, this file is not in the right folder.
 * ──────────────────────────────────────────────────────────────────────────────
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit; // no direct access
}

add_action( 'init', function () {

    // The Rank Math meta keys we want to be writable through the REST API.
    $keys = array(
        'rank_math_title',           // SEO title (the <title> tag)
        'rank_math_description',      // meta description
        'rank_math_focus_keyword',    // focus keyword(s), comma-separated
        'rank_math_canonical_url',    // canonical URL (optional)
    );

    // Register the meta for regular posts. Add 'page' or custom types here if needed.
    $post_types = array( 'post' );

    foreach ( $post_types as $ptype ) {
        foreach ( $keys as $key ) {
            register_post_meta( $ptype, $key, array(
                'type'          => 'string',
                'single'        => true,
                'show_in_rest'  => true,
                'auth_callback' => function () {
                    // Only users who can edit posts may write these via the API.
                    return current_user_can( 'edit_posts' );
                },
            ) );
        }
    }
} );
